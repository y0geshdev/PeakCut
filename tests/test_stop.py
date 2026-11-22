"""Stopping ordinary videos: drain work, delete generated files, remember the source choice, never restart."""
import contextlib
import io
import json
import os
import sys
import tempfile
import threading
from pathlib import Path
from unittest.mock import patch

import numpy as np
from fastapi import HTTPException
from fastapi.testclient import TestClient

sys.path.insert(0, ".")


def check(name, condition):
    if not condition:
        raise AssertionError(name)
    print("PASS " + name)


def rejected(fn, exception=ValueError):
    try:
        fn()
    except exception:
        return True
    return False


def main(data):
    os.environ.update(PEAKCUT_DATA=data, DATABASE_URL="", PEAKCUT_ACCOUNTS="0", PEAKCUT_FETCH_MODEL="0",
                      PEAKCUT_PUBLIC_URL="http://testserver")
    from studio import account, accounts, auth, brain, config, creators, ctx, db, jobs, media, posting, render, server, transcribe

    db.init()
    uid = auth.local_user().id
    jobs._q = jobs._FairQueue()

    def video(source=True, creator=None):
        job = jobs.create({"type": "file", "name": "Test video"}, {"captions": False}, enqueue=False, creator=creator)
        d = Path(job["dir"])
        if source:
            (d / "source.mp4").write_bytes(b"whole source")
            job["source"]["path"] = str(d / "source.mp4")
            job["source_path"] = str(d / "source.mp4")
        (d / "clips").mkdir(exist_ok=True)
        for name in ("clip1.mp4", "clip1.jpg", "clip1.ass", "clip1.json", "clip1.src.mp4", "clip1.wav"):
            (d / "clips" / name).write_bytes(b"generated")
        for name in ("words.json", "words_en.json", "thumb.jpg", "audio.wav", "source.mp4.part", "error.log"):
            (d / name).write_bytes(b"generated")
        (d / "intermediate").mkdir()
        (d / "intermediate" / "temporary").write_bytes(b"generated")
        job.update(clips=[{"id": "clip1", "status": "done", "file": "clip1.mp4", "cover": "clip1.jpg",
                           "title": "Clip", "description": "", "score": 80}], ai={"tokens": 9}, width=1920,
                   height=1080, duration=30, done_blocks=1, facecam=[0, 0, 100, 100])
        jobs.save(job)
        return job

    def finished(job):
        with jobs._work_cv:
            ready = jobs._work_cv.wait_for(lambda: job["id"] not in jobs._stoppers, timeout=10)
        check("cleanup worker finishes", ready and job["status"] == "stopped")

    def post(job, status="scheduled", user=None):
        p = {"id": str(len(posting._posts)), "job": job["id"], "clip": "clip1", "user": user or uid,
             "creator": None, "account": "acc1", "account_name": "Test", "platform": "youtube", "status": status,
             "tries": 0, "due_at": 0, "title": "Clip", "url": "https://example.test/published", "remote_id": "published"}
        posting._posts.append(p)
        return p

    with ctx.as_user(uid):
        # Both settings paths accept 500 and still clamp larger values and retain the default.
        for cap, want in ((500, 500), (501, 500), (9999, 500), (0, 1)):
            check(f"video options clamp {cap} to {want}", jobs.clean_options({"max_clips": cap})["max_clips"] == want)
        c = creators.create({"name": "Stop tests", "max_clips": 500})
        check("a creator accepts 500 clips", c["max_clips"] == 500)
        check("a creator clamps above 500", creators.update(c["id"], {"max_clips": 501})["max_clips"] == 500)
        inherited = jobs.create({"type": "file", "name": "Inherited"}, {}, enqueue=False, creator=c["id"])
        check("a video inherits its creator's 500-clip setting", inherited["options"]["max_clips"] == 500)
        ordinary = jobs.create({"type": "file", "name": "Default"}, {}, enqueue=False)
        check("the default stays at 6", ordinary["options"]["max_clips"] == 6 and creators.DEFAULTS["max_clips"] == 6)

        shared = creators.root(c["id"]) / "logo.png"
        shared.write_bytes(b"shared logo")
        external = Path(data) / "original.mp4"
        external.write_bytes(b"original")
        for keep in (True, False):
            j = video(creator=c["id"])
            d = Path(j["dir"])
            jobs.enqueue(j)
            jobs._q.put(("clip", j["id"], "clip1"))
            scheduled = post(j)
            published = post(j, "posted")
            someone_else = post(j, user="another-user")
            before = ctx.version()
            jobs.stop(j["id"], keep)
            finished(j)
            check("queued job and remake are both removed", j["id"] not in jobs._q.ahead()
                  and all(x[1] != j["id"] for x in jobs._q.quick))
            check("only the stopped record and optional whole source remain",
                  {p.name for p in d.iterdir()} == {"job.json", "stop.json"} | ({"source.mp4"} if keep else set()))
            check("generated metadata is gone", j["clips"] == [] and j["ai"] == {} and "facecam" not in j and "done_blocks" not in j)
            check("the source choice is reflected on the job", j["source_kept"] is keep)
            check("pending posts are cancelled and published videos left alone",
                  scheduled["status"] == "cancelled" and published["status"] == "posted" and published["remote_id"] == "published")
            check("another user's posts are not cancelled", someone_else["status"] == "scheduled")
            check("cancelled posts cannot be retried for a stopped video", rejected(lambda: posting.retry(scheduled["id"])))
            check("no new work can start", rejected(lambda: jobs.enqueue(j), jobs.Stopped)
                  and rejected(lambda: jobs.request_render(j["id"], "clip1", {}), jobs.Stopped))
            check("sync reports the stop", ctx.version() > before)
            check("creator settings and shared logos survive", shared.exists() and (creators.root(c["id"]) / "creator.json").exists())
            jobs._load_file(d / "job.json", uid)
            loaded = jobs.get(j["id"])
            check("a finished stop does not resume on load", loaded["status"] == "stopped" and not loaded.get("resume"))

        j = video(source=False)
        j["source"].update(type="file", path=str(external))
        jobs.save(j)
        jobs.stop(j["id"], False)
        finished(j)
        check("an external original is never deleted", external.read_bytes() == b"original")

        j = video(source=False)
        j["source"] = {"type": "url", "name": "Long link", "url": "https://youtube.com/watch?v=test"}
        jobs.stop(j["id"], True)
        finished(j)
        check("missing complete sources are explained, not partial files kept",
              not j["source_kept"] and "No complete source" in j["stage"]
              and {p.name for p in Path(j["dir"]).iterdir()} == {"job.json", "stop.json"})

        # A worker may finish writing after Stop, but cleanup cannot pass it.
        j = video()
        j["status"] = "running"
        entered, release = threading.Event(), threading.Event()
        errors = []

        def writer():
            try:
                with jobs.work(j):
                    entered.set()
                    release.wait(10)
                    (Path(j["dir"]) / "late.tmp").write_bytes(b"late artifact")
                    jobs._set(j, status="done")
            except jobs.Stopped:
                pass
            except Exception as e:
                errors.append(e)

        thread = threading.Thread(target=ctx.bind(writer))
        thread.start()
        check("the active worker starts", entered.wait(5))
        jobs.stop(j["id"], False)
        check("active workers keep the files in place while stopping", j["status"] == "stopping" and (Path(j["dir"]) / "clips").exists())
        check("manual deletion is blocked while stopping", rejected(lambda: account.delete_clip(j["id"], "clip1"), account.Busy)
              and rejected(lambda: server.delete_job(j["id"]), HTTPException))
        release.set()
        thread.join(10)
        finished(j)
        check("late artifacts are removed, not recreated, and completion cannot overwrite Stop",
              not errors and not thread.is_alive() and not (Path(j["dir"]) / "late.tmp").exists())

        # Simulate restarting between persisting Stop and cleaning files, including a damaged job manifest.
        for damaged in (False, True):
            j = video()
            d = Path(j["dir"])
            with patch.object(jobs, "_start_stop"):
                jobs.stop(j["id"], False)
            old = dict(j, status="running", resume=True, remake=["clip1"])
            old.pop("stop")
            (d / "job.json").write_text("broken" if damaged else json.dumps(old), encoding="utf-8")
            jobs._jobs.pop(j["id"])
            jobs._by_user[uid].pop(j["id"])
            jobs._load_file(d / "job.json", uid)
            restarted = jobs.get(j["id"])
            check("restart recovers the source choice without resuming",
                  restarted["status"] == "stopping" and restarted["stop"] == {"keep_source": False}
                  and not restarted.get("resume") and not restarted.get("remake"))
            jobs._pick_up_after_restart()
            finished(restarted)
            check("restart completes deletion, including the source", not (d / "source.mp4").exists()
                  and restarted["id"] not in jobs._q.ahead())

        # A cleanup failure stays visible and retry uses the original choice.
        j = video()
        original_unlink = Path.unlink

        def busy(p, *args, **kwargs):
            if p == Path(j["dir"]) / "words.json":
                raise PermissionError("file is busy")
            return original_unlink(p, *args, **kwargs)

        with patch.object(Path, "unlink", busy), patch.object(jobs.traceback, "print_exc") as reported:
            jobs.stop(j["id"], False)
            with jobs._work_cv:
                ready = jobs._work_cv.wait_for(lambda: j["id"] not in jobs._stoppers, timeout=10)
            check("failed cleanup is not falsely marked stopped", ready and j["status"] == "stopping" and bool(j["error"]))
            check("the cleanup failure is also logged", reported.called)
        jobs.stop(j["id"], True)
        finished(j)
        check("retry retains the original delete-source choice", j["stop"]["keep_source"] is False and not j["source_kept"])

        j = video()
        with patch.object(jobs, "_write_stop", side_effect=OSError("disk full")):
            check("a stop that cannot be persisted is reported", rejected(lambda: jobs.stop(j["id"]), OSError))
        check("failed persistence starts no cleanup", j["status"] == "queued" and not j.get("stop")
              and (Path(j["dir"]) / "clips").exists())

        # Staging lives outside the job directory; its association must survive a restart too.
        unrelated = server._up_root() / ("up-" + os.urandom(12).hex())
        unrelated.mkdir()
        (unrelated / "meta.json").write_text(json.dumps({"user": "another-user"}), encoding="utf-8")
        for pieces in (False, True, "partially-removed"):
            j = video(source=False)
            if pieces:
                upid = os.urandom(12).hex()
                staging = server._up_root() / f"up-{upid}"
                staging.mkdir()
                if pieces != "partially-removed":
                    (staging / "meta.json").write_text(json.dumps({"user": uid}), encoding="utf-8")
                (staging / "00000.part").write_bytes(b"piece")
                j["source"]["upload_id"] = upid
            else:
                staging = server._up_root() / (os.urandom(8).hex() + ".mp4")
                staging.write_bytes(b"source")
                j["source"]["upload_file"] = staging.name
            jobs.save(j)
            with patch.object(jobs, "_start_stop"):
                jobs.stop(j["id"], True)
            jobs._load_file(Path(j["dir"]) / "job.json", uid)
            loaded = jobs.get(j["id"])
            jobs._pick_up_after_restart()
            finished(loaded)
            check("restart removes only this video's unfinished upload", not staging.exists() and unrelated.exists())

        j = video(source=False)
        j["source"]["upload_id"] = unrelated.name.removeprefix("up-")
        with patch.object(jobs.traceback, "print_exc") as reported:
            jobs.stop(j["id"], False)
            with jobs._work_cv:
                jobs._work_cv.wait_for(lambda: j["id"] not in jobs._stoppers, timeout=10)
            check("cleanup refuses an upload owned by someone else",
                  unrelated.exists() and j["status"] == "stopping" and bool(j["error"]) and reported.called)
        j["source"].pop("upload_id")
        jobs.stop(j["id"], False)
        finished(j)

        with tempfile.TemporaryDirectory(prefix="pk") as work:
            j = video()
            folder = Path(work)
            (folder / "frames").mkdir()
            (folder / "frames" / "frame.png").write_bytes(b"frame")
            j["render_work"] = [str(folder)]
            with patch.object(jobs, "_start_stop"):
                jobs.stop(j["id"], False)
            old = dict(j)
            old.pop("render_work")
            (Path(j["dir"]) / "job.json").write_text(json.dumps(old), encoding="utf-8")
            jobs._load_file(Path(j["dir"]) / "job.json", uid)
            loaded = jobs.get(j["id"])
            jobs._pick_up_after_restart()
            finished(loaded)
            check("restart removes remembered short rendering folders", not folder.exists())

        j = video()
        render_folder = None
        with patch.object(jobs.shutil, "rmtree", side_effect=PermissionError("Temporary folder is still open.")):
            try:
                with jobs.work(j), jobs._render_work(j) as render_folder:
                    (render_folder / "clip.mp4").write_bytes(b"generated")
            except PermissionError:
                pass
        check("a temporary-folder cleanup failure preserves its recovery record",
              render_folder.exists() and j["render_work"] == [str(render_folder)])
        with patch.object(jobs.shutil, "rmtree", side_effect=PermissionError("Temporary folder is still open.")), \
             patch.object(jobs.traceback, "print_exc") as reported:
            jobs.stop(j["id"], False)
            with jobs._work_cv:
                jobs._work_cv.wait_for(lambda: j["id"] not in jobs._stoppers, timeout=10)
            check("temporary-folder cleanup failures remain visible and retryable",
                  j["status"] == "stopping" and bool(j["error"]) and reported.called)
        jobs.stop(j["id"], True)
        finished(j)
        check("retry cleans the tracked temporary folder and retains the source choice",
              not render_folder.exists() and not j["source_kept"])

        j = video()
        entered, release = threading.Event(), threading.Event()

        def finish_log(*args):
            entered.set()
            release.wait(10)

        with patch.object(creators, "log", side_effect=finish_log):
            jobs.stop(j["id"], False)
            check("stop cleanup reaches its last storage operation", entered.wait(5))
            check("manual deletion waits for the cleanup worker itself",
                  jobs.is_busy(j) and rejected(lambda: server.delete_job(j["id"]), HTTPException))
            release.set()
            finished(j)

        # Stop while joining uploaded pieces: keep-source must not keep an incomplete assembly.
        with patch.object(config, "UPLOAD_PART_MB", 1):
            upload = server.upload_start({"name": "pieces.mp4", "size": 2 * 1024 * 1024})
        staging = server._up_root() / f"up-{upload['id']}"
        for n in range(2):
            (staging / f"{n:05d}.part").write_bytes(b"x" * upload["part"])
        entered, release = threading.Event(), threading.Event()
        original_copy = server.shutil.copyfileobj
        upload_errors = []

        def assemble(src, out, *args):
            original_copy(src, out, *args)
            entered.set()
            release.wait(10)

        def finish_upload():
            try:
                server.upload_finish(upload["id"])
            except Exception as e:
                upload_errors.append(e)

        with patch.object(server.shutil, "copyfileobj", side_effect=assemble):
            t = threading.Thread(target=ctx.bind(finish_upload))
            t.start()
            check("the upload starts assembling", entered.wait(5))
            j = next(j for j in jobs.all_jobs() if j["source"].get("upload_id") == upload["id"])
            jobs.stop(j["id"], True)
            release.set()
            t.join(10)
        finished(j)
        check("an interrupted assembly does not enqueue or preserve an incomplete source",
              not upload_errors and not t.is_alive() and not staging.exists()
              and not j["source_kept"] and j["id"] not in jobs._q.ahead())

        entered, release = threading.Event(), threading.Event()
        original_move = server.shutil.move
        upload_errors = []

        def move(*args, **kwargs):
            entered.set()
            release.wait(10)
            return original_move(*args, **kwargs)

        def direct_upload():
            try:
                server.create_from_file(server.UploadFile(filename="direct.mp4", file=io.BytesIO(b"whole upload")), "{}", "")
            except Exception as e:
                upload_errors.append(e)

        with patch.object(server.shutil, "move", side_effect=move):
            t = threading.Thread(target=ctx.bind(direct_upload))
            t.start()
            check("the direct upload starts moving its complete source", entered.wait(5))
            j = next(j for j in jobs.all_jobs() if j["source"].get("name") == "direct.mp4")
            jobs.stop(j["id"], True)
            release.set()
            t.join(10)
        finished(j)
        check("a complete direct upload finishing during Stop is kept without enqueueing",
              not upload_errors and not t.is_alive() and j["source_kept"]
              and Path(j["source_path"]).read_bytes() == b"whole upload" and j["id"] not in jobs._q.ahead())

        # Uploads already reading the clip are drained; successful remote posts are never undone.
        for fails in (False, True):
            j = video()
            j["status"] = "running"
            p = post(j, "posting")
            started, release = threading.Event(), threading.Event()
            read_ok = []

            def upload(acc, path, *args):
                started.set()
                release.wait(10)
                read_ok.append(path.read_bytes() == b"generated")
                if fails:
                    raise RuntimeError("upload failed")
                return "remote", "https://example.test/remote"

            with patch.object(accounts, "get", return_value={"platform": "youtube", "name": "Test"}), \
                 patch.object(accounts, "youtube_upload", side_effect=upload):
                t = threading.Thread(target=ctx.bind(lambda: posting._post(p)))
                t.start()
                check("a posting operation starts reading", started.wait(5))
                jobs.stop(j["id"], False)
                check("cleanup waits for the posting operation", j["status"] == "stopping" and (Path(j["dir"]) / "clips" / "clip1.mp4").exists())
                release.set()
                t.join(10)
            finished(j)
            check("the uploader can finish reading before files are removed", read_ok == [True] and not t.is_alive())
            check("a failed upload is cancelled without retry; a published upload survives",
                  p["status"] == ("cancelled" if fails else "posted"))

        # Exercise the real pipeline at long-running boundaries, including download/transcription/render errors.
        words = [{"w": "word", "s": i * 0.5, "e": i * 0.5 + 0.4} for i in range(20)]
        for boundary, raises in (("download", False), ("download", True), ("transcribe", True), ("ai", False), ("render", True)):
            j = video(source=False)
            d = Path(j["dir"])
            j["source"] = {"type": "url", "url": "https://youtube.com/watch?v=test", "name": "Test"}
            started, release = threading.Event(), threading.Event()
            calls = []
            render_folders = []

            def gate(where):
                calls.append(where)
                if where == boundary:
                    started.set()
                    if not release.wait(10):
                        raise RuntimeError("test worker was not released")
                    if raises:
                        raise RuntimeError("simulated " + where + " failure")

            def download(url, folder, quality):
                gate("download")
                out = folder / "source.mp4"
                out.write_bytes(b"whole source")
                return out

            def audio(url, folder, progress=None):
                out = folder / "audio_src.m4a"
                out.write_bytes(b"audio")
                return out

            def transcript(*a, **k):
                gate("transcribe")
                return words

            def select(*a, **k):
                gate("ai")
                return [{"start": 0, "end": 10, "title": "Clip", "description": "", "hashtags": [],
                         "score": 80, "hook": "Hook"}], {"tokens": 1}

            def cut(*a, **k):
                render_folders.append(k["work_dir"])
                gate("render")
                (d / "clips" / "late.mp4").write_bytes(b"late")
                return {"file": "late.mp4"}

            with contextlib.ExitStack() as stack:
                mocks = [(transcribe, "model_ready", {"return_value": True}),
                         (config, "YT_TRANSCRIPT", {"new": False}), (config, "SKIP_STATIC", {"new": False}),
                         (media, "info", {"return_value": {"kind": "video", "title": "Test", "uploader": "",
                                                           "duration": 30, "is_live": False}}),
                         (media, "download", {"side_effect": download}),
                         (media, "download_audio", {"side_effect": audio}),
                         (media, "extract_audio", {"side_effect": lambda src, out: out.write_bytes(b"audio")}),
                         (media, "load_audio", {"return_value": np.zeros(30 * 16000, dtype=np.int16)}),
                         (media, "probe", {"return_value": {"duration": 30, "width": 1920, "height": 1080}}),
                         (media, "save_thumb", {"return_value": False}),
                         (media, "download_section", {"side_effect": AssertionError("must not retry with pieces")}),
                         (transcribe, "transcribe", {"side_effect": transcript}),
                         (brain, "find_clips", {"side_effect": select}), (jobs, "_facecam", {"return_value": None}),
                         (render, "render_clip", {"side_effect": cut})]
                for module, name, options in mocks:
                    stack.enter_context(patch.object(module, name, **options))
                pipeline_errors = []

                def process():
                    try:
                        jobs._process(j, "job", None)
                    except jobs.Stopped:
                        pass
                    except Exception as e:
                        pipeline_errors.append(e)

                t = threading.Thread(target=ctx.bind(process))
                t.start()
                try:
                    check(f"the pipeline reaches {boundary}", started.wait(5))
                    jobs.stop(j["id"], True)
                    check(f"cleanup drains {boundary} before removing files", j["status"] == "stopping" and d.exists())
                finally:
                    release.set()
                    t.join(10)
                finished(j)
                check(f"{boundary} cannot restart the pipeline or leave late files",
                      not t.is_alive() and not pipeline_errors and calls.count("download") == 1
                      and {x.name for x in d.iterdir()} <= {"job.json", "stop.json", "source.mp4"})
                if boundary == "download" and not raises:
                    check("a complete download finishing during Stop is kept", j["source_kept"] and (d / "source.mp4").read_bytes() == b"whole source")
                if boundary == "render":
                    check("a failed renderer leaves no short temporary folder", render_folders and all(not f.exists() for f in render_folders))

        # API ownership, validation, and signed readers are covered without starting real workers.
        j = video()
        with ctx.as_user("other-user"):
            try:
                server.stop_job(j["id"], {"keep_source": False})
                status = 0
            except HTTPException as e:
                status = e.status_code
        check("one user cannot stop another user's video", status == 404 and j["status"] == "queued")
        live_job = jobs.create({"type": "file", "name": "Live"}, {}, enqueue=False, kind="live")
        check("ordinary Stop does not change live Stop", rejected(lambda: jobs.stop(live_job["id"]), ValueError) and live_job["status"] == "queued")
        client = TestClient(server.app)
        client.headers["Origin"] = "http://testserver"
        check("the API validates a real checkbox value", client.post(f"/api/jobs/{j['id']}/stop", json={"keep_source": "yes"}).status_code == 409)
        r = client.post(f"/api/jobs/{j['id']}/stop", json={"keep_source": True})
        check("the stop API returns the job without private storage paths", r.status_code == 200 and "dir" not in r.json() and "source_path" not in r.json())
        finished(j)
        reader_job = video()
        link = accounts.clip_link(reader_job["id"], "clip1.mp4")
        check("signed platform reads release their file lease", client.get(link).status_code == 200 and not jobs._active.get(reader_job["id"]))
        with jobs.work(reader_job):
            jobs.stop(reader_job["id"], False)
            check("a platform upload already in progress can still fetch its signed file", client.get(link).status_code == 200)
        finished(reader_job)
        check("signed links cannot read deleted files after Stop", client.get(link).status_code == 404)
        check("there are no workers left using test files", not jobs._active and not jobs._stoppers)
    db.engine.dispose()


with tempfile.TemporaryDirectory(prefix="pc-stop-") as data:
    main(data)
