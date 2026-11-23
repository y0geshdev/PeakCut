"""Re-processing a video's clips: the failed ones only, or every clip with new settings.

Runs against the code directly, with its own empty data folder."""
import os
import sys
import tempfile

sys.path.insert(0, ".")


def check(name, condition):
    if not condition:
        raise AssertionError(name)
    print("PASS " + name)


def main(data):
    os.environ.update(PEAKCUT_DATA=data, DATABASE_URL="", PEAKCUT_ACCOUNTS="0", PEAKCUT_FETCH_MODEL="0",
                      PEAKCUT_PUBLIC_URL="http://testserver")
    from fastapi.testclient import TestClient
    from studio import auth, ctx, db, jobs, server

    db.init()
    uid = auth.local_user().id
    jobs._q = jobs._FairQueue()

    with ctx.as_user(uid):
        job = jobs.create({"type": "file", "name": "Test video"}, {"captions": True}, enqueue=False)
        job.update(status="done", stage="Done", clips=[
            {"id": "c1", "status": "done", "title": "One", "start": 0, "end": 30, "style": "bounce", "layout": "blur", "captions": True},
            {"id": "c2", "status": "error", "error": "Encoding failed", "title": "Two", "start": 30, "end": 60, "style": "bounce", "layout": "blur", "captions": True},
            {"id": "c3", "status": "done", "title": "Three", "start": 60, "end": 90, "style": "bounce", "layout": "blur", "captions": True},
        ])
        jobs.save(job)

        client = TestClient(server.app)
        client.headers["Origin"] = "http://testserver"

        r = client.post(f"/api/jobs/{job['id']}/clips/reprocess", json={"mode": "nope"})
        check("an unknown mode is rejected", r.status_code == 400)

        r = client.post(f"/api/jobs/{job['id']}/clips/reprocess", json={"mode": "failed"})
        check("failed-only re-processes just the error clip", r.status_code == 200
              and [c["status"] for c in jobs.get(job["id"])["clips"]] == ["done", "queued", "done"])

        r = client.post(f"/api/jobs/{job['id']}/clips/reprocess", json={"mode": "failed"})
        check("nothing left to retry is a 400", r.status_code == 400)

        for c in jobs.get(job["id"])["clips"]:
            c["status"] = "done"
        jobs.save(jobs.get(job["id"]))
        r = client.post(f"/api/jobs/{job['id']}/clips/reprocess",
                        json={"mode": "all", "options": {"style": "hype", "layout": "zoom", "captions": False, "logo": None}})
        clips = jobs.get(job["id"])["clips"]
        check("all clips are re-queued with the new settings", r.status_code == 200
              and all(c["status"] == "queued" and c["style"] == "hype" and c["layout"] == "zoom" and c["captions"] is False
                      and c.get("logo") is None for c in clips))

        r = client.post(f"/api/jobs/{job['id']}/clips/reprocess", json={"mode": "all", "options": {}})
        check("nothing to do when every clip is already queued is a 400", r.status_code == 400)
        for c in jobs.get(job["id"])["clips"]:
            c["status"] = "done"
        jobs.save(jobs.get(job["id"]))

        r = client.post(f"/api/jobs/{job['id']}/clips/reprocess",
                        json={"mode": "all", "options": {"start": 0, "end": 5000}})
        check("a nonsensical clip length is a 400", r.status_code == 400)

        jobs.get(job["id"]).update(status="running")
        jobs.save(jobs.get(job["id"]))
        r = client.post(f"/api/jobs/{job['id']}/clips/reprocess", json={"mode": "all", "options": {}})
        check("a video still being worked on is a 409", r.status_code == 409)

        r = client.post("/api/jobs/no-such-job/clips/reprocess", json={"mode": "all", "options": {}})
        check("an unknown video is a 404", r.status_code == 404)
    db.engine.dispose()


with tempfile.TemporaryDirectory(prefix="pc-reprocess-") as data:
    main(data)
