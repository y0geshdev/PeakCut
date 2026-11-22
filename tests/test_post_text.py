"""The post text of a clip: the AI writes a new title, description and hashtags on request, the person can change
them, and posting uses what they saved, all without making the clip again. No AI key is needed: the AI is replaced."""
import json
import os
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException

sys.path.insert(0, ".")
SAID = "no way he just hit that shot from across the whole map are you kidding me"
WORDS = [{"w": w, "s": i * 0.5, "e": i * 0.5 + 0.4} for i, w in enumerate(SAID.split())]
WORDS.append({"w": "LATER", "s": 50.0, "e": 50.4})           # said after the clip ends: never sent to the AI
GOOD = {"start": 0, "end": 0, "score": 70, "hook": "NO WAY", "title": "The shot nobody expected",
        "description": "He hits it from across the map. Visit www.example.com or ask @someone",
        "hashtags": ["#gaming", "clutch shot", "fps"], "reason": "r"}


def check(name, condition):
    if not condition:
        raise AssertionError(name)
    print(f"PASS {name}")


def fails_with(call, status, word=""):
    try:
        call()
    except HTTPException as e:
        return e.status_code == status and word.lower() in str(e.detail).lower()
    return False


def main(data):
    os.environ.update(PEAKCUT_DATA=data, DATABASE_URL="", PEAKCUT_ACCOUNTS="0")
    from studio import auth, brain, creators, ctx, db, jobs, posting, server

    db.init()
    try:
        # ---- the AI's answer, in each shape services send it
        with patch.object(brain, "ask_ai", return_value=([GOOD], "m", 10)) as ai:
            t = brain.post_text(SAID)
            check("the AI's answer becomes a title, description and hashtags", set(t) == {"title", "description", "hashtags"}
                  and t["title"] == "The shot nobody expected")
            check("links and @handles never reach the post text", "example.com" not in t["description"] and "@" not in t["description"])
            check("hashtags come back as plain words", t["hashtags"] == ["gaming", "clutchshot", "fps"])
            check("what is said goes to the AI inside the transcript tags", SAID in ai.call_args.args[0]
                  and "<transcript>" in ai.call_args.args[0])
        with patch.object(brain, "ask_ai", return_value=(GOOD, "m", 10)):
            check("a service that sends one clip instead of a list still works", brain.post_text(SAID)["title"] == GOOD["title"])
            check("a hand-made clip also accepts one clip instead of a list", brain.describe(SAID)["title"] == GOOD["title"])
        for bad in ([], {}, [{"title": "", "description": ""}], ["just words"], None):
            with patch.object(brain, "ask_ai", return_value=(bad, "m", 10)):
                try:
                    brain.post_text(SAID)
                    ok = False
                except RuntimeError as e:
                    ok = "usable" in str(e)
                check(f"an answer with nothing usable ({bad!r}) is a clear error", ok)
        try:
            brain.post_text("too short")
            ok = False
        except ValueError:
            ok = True
        check("a clip with almost no speech says so instead of asking the AI", ok)

        user = auth.local_user().id
        with ctx.as_user(user):
            creator = creators.create({"name": "Posting rules", "post_gap_min": "1", "daily_cap": "500"})
            check("posting settings accept one minute and 500 posts per day",
                  creator["post_gap_min"] == 1 and creator["daily_cap"] == 500)
            creators.forget(user)
            creator = creators.get(creator["id"])
            check("posting settings survive saving and reloading without being reset",
                  creator["post_gap_min"] == 1 and creator["daily_cap"] == 500)

            now = time.mktime((2026, 1, 2, 12, 0, 0, 0, 0, -1))
            posts = [{"user": user, "account": "test-account", "status": "posted", "posted_at": now, "due_at": now}
                     for _ in range(499)]
            with patch.object(posting, "_posts", posts), patch.object(posting.time, "time", return_value=now):
                check("the scheduler permits the 500th daily post with a one-minute gap",
                      posting._next_slot("test-account", creator["post_gap_min"], creator["daily_cap"]) == now + 60)
                posts.append(dict(posts[0]))
                check("the scheduler still respects the chosen daily limit",
                      posting._day(posting._next_slot("test-account", creator["post_gap_min"], creator["daily_cap"]))
                      > posting._day(now))

            creator = creators.update(creator["id"], {"post_gap_min": "0", "daily_cap": "1000000"})
            check("posting settings have no fixed daily ceiling and permit zero spacing",
                  creator["post_gap_min"] == 0 and creator["daily_cap"] == 1000000)
            with patch.object(posting, "_posts", posts), patch.object(posting.time, "time", return_value=now):
                check("zero spacing adds no delay even after 500 posts today",
                      posting._next_slot("test-account", creator["post_gap_min"], creator["daily_cap"]) == now)
            creator = creators.update(creator["id"], {"post_gap_min": "-1", "daily_cap": "0"})
            check("posting settings remain nonnegative with a positive daily limit",
                  creator["post_gap_min"] == 0 and creator["daily_cap"] == 1)

        # ---- a finished clip
        clip = {"id": "clip1", "start": 0.0, "end": 8.0, "status": "done", "hook": "NO WAY", "title": "Old title",
                "description": "Old words", "hashtags": ["old"], "score": 80, "version": 1, "file": "clip1.mp4"}
        with ctx.as_user(user):
            job = jobs.create({"type": "file", "name": "Post text test"}, {}, enqueue=False)
            job.update(status="done", title="My stream", duration=60.0, width=1920, height=1080, clips=[clip])
            jobs.save(job)
        d = Path(job["dir"])
        (d / "words.json").write_text(json.dumps(WORDS), encoding="utf-8")
        (d / "clips").mkdir(exist_ok=True)
        (d / "clips" / "clip1.json").write_text(json.dumps({"title": "Old title", "score": 80}), encoding="utf-8")

        with ctx.as_user(user), patch.object(jobs._q, "put") as queue:
            with patch.object(brain, "ask_ai", return_value=([GOOD], "m", 10)) as ai:
                out = server.clip_write(job["id"], "clip1")
            prompt = ai.call_args.args[0]
            check("Write again with AI sends only the words said in the clip", SAID in prompt and "LATER" not in prompt)
            check("the video's title goes along as context", "My stream" in prompt)
            check("the new text comes back to the page", out["title"] == GOOD["title"])
            check("the new text is not saved until the person posts or saves", clip["title"] == "Old title")
            check("a stream with no game gets no game rules", "This stream is" not in prompt)

            job["game"] = "gta 6"
            with patch.object(brain, "ask_ai", return_value=([GOOD], "m", 10)) as ai:
                server.clip_write(job["id"], "clip1")
            check("on a game stream, Write again with AI reads the same game rules", "This stream is Grand Theft Auto VI" in ai.call_args.args[0])
            with patch.object(brain, "ask_ai", return_value=([GOOD], "m", 10)) as ai:
                brain.describe(SAID, game="gta 6")
            check("a hand-made clip reads the game rules the same way", "This stream is Grand Theft Auto VI" in ai.call_args.args[0])
            job.pop("game")

            with patch.object(brain, "ask_ai", side_effect=RuntimeError("The AI is not set up on this server.")):
                check("no AI set up: a clear error, not a crash", fails_with(lambda: server.clip_write(job["id"], "clip1"), 503, "not set up"))

            server.clip_text(job["id"], "clip1", {"title": "My own title", "description": "My own words", "hashtags": "#funny  gaming #fps"})
            check("the person's title and description are saved", clip["title"] == "My own title" and clip["description"] == "My own words")
            check("typed hashtags are saved as plain words", clip["hashtags"] == ["funny", "gaming", "fps"])
            check("saving the post text does not make the clip again", not queue.called and clip["status"] == "done" and clip["version"] == 1)
            saved = json.loads((d / "job.json").read_text(encoding="utf-8"))["clips"][0]
            check("the change is kept on disk", saved["title"] == "My own title" and saved["hashtags"] == ["funny", "gaming", "fps"])
            side = json.loads((d / "clips" / "clip1.json").read_text(encoding="utf-8"))
            check("the copy next to the video file has the new text too", side["title"] == "My own title" and side["score"] == 80)
            check("posting uses the saved text", "My own words" in posting._caption(clip, {"post_footer": ""})
                  and "#funny #gaming #fps" in posting._caption(clip, {"post_footer": ""}))

            server.clip_text(job["id"], "clip1", {"title": "x" * 500})
            check("a very long title is cut to fit", len(clip["title"]) == 100 and clip["description"] == "My own words")
            check("hashtags that are not words or a list are refused",
                  fails_with(lambda: server.clip_text(job["id"], "clip1", {"hashtags": {"a": 1}}), 400, "hashtags"))
            check("an unknown clip is not found", fails_with(lambda: server.clip_text(job["id"], "nope", {"title": "x"}), 404))

            # A clip whose description already ends with its hashtags (how clips are made now)
            clip.update(description="Old words\n\n#old #tags", hashtags=["old", "tags"], hashtags_in_description=True)
            server.clip_text(job["id"], "clip1", {"description": "New words\n\n#old #tags", "hashtags": "new tags"})
            check("changed hashtags replace the line at the end of the description",
                  clip["description"] == "New words\n\n#new #tags" and clip["hashtags"] == ["new", "tags"])
            check("and are posted once, not twice", posting._caption(clip, {"post_footer": ""}).count("#new") == 1)
            server.clip_text(job["id"], "clip1", {"description": "Only words, from the AI"})
            check("a description without its tags gets them back at the end",
                  clip["description"] == "Only words, from the AI\n\n#new #tags")
            clip.pop("hashtags_in_description")

            server.rerender(job["id"], "clip1", {"hashtags": "#one two"})
            check("Save and re-make also keeps typed hashtags", clip["hashtags"] == ["one", "two"])

        with ctx.as_user("someone-else"):
            check("someone else cannot change this clip's text",
                  fails_with(lambda: server.clip_text(job["id"], "clip1", {"title": "hacked"}), 404))
            with patch.object(brain, "ask_ai", return_value=([GOOD], "m", 10)) as ai:
                check("someone else cannot ask the AI about this clip",
                      fails_with(lambda: server.clip_write(job["id"], "clip1"), 404) and not ai.called)

        with ctx.as_user(user), patch.object(brain, "ask_ai", return_value=([GOOD], "m", 10)):
            stopped = any(fails_with(lambda: server.clip_write(job["id"], "clip1"), 429) for _ in range(21))
            check("asking the AI over and over is limited", stopped)
    finally:
        db.engine.dispose()


if __name__ == "__main__":
    with tempfile.TemporaryDirectory(prefix="pc-posttext-") as data:
        main(data)
