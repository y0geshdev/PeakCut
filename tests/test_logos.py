"""Logo uploads, creator defaults, clip overrides and actual rendered pixels. No outside services."""
import io
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException
from fastapi.testclient import TestClient
from PIL import Image

sys.path.insert(0, ".")


def check(name, condition):
    if not condition:
        raise AssertionError(name)
    print(f"PASS {name}")


def png(image):
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def main(data):
    os.environ.update(PEAKCUT_DATA=data, DATABASE_URL="", PEAKCUT_ACCOUNTS="0",
                      PEAKCUT_PUBLIC_URL="http://127.0.0.1:8765")
    from studio import auth, config, creators, ctx, db, jobs, live, logos, render, server

    db.init()
    try:
        client = TestClient(server.app, base_url=config.PUBLIC_URL)
        origin = {"Origin": config.PUBLIC_URL}
        user = auth.local_user().id
        image = Image.new("RGBA", (200, 100), (255, 0, 0, 255))
        image.paste((255, 0, 0, 0), (0, 0, 50, 100))
        image.paste((255, 0, 0, 128), (150, 0, 200, 100))
        response = client.post("/api/logos", files={"file": ("logo.png", png(image), "image/png")}, headers=origin)
        check("a transparent logo can be uploaded", response.status_code == 200)
        logo = response.json()
        response = client.get(f"/api/logos/{logo['id']}")
        with Image.open(io.BytesIO(response.content)) as uploaded:
            check("uploads retain their transparency and shape",
                  response.status_code == 200 and uploaded.size == (200, 100) and uploaded.getpixel((20, 50))[3] == 0)
        noise = png(Image.frombytes("RGB", (512, 512), os.urandom(512 * 512 * 3)))
        response = client.post("/api/logos", files={"file": ("logo.png", noise, "image/png")}, headers=origin)
        check("logo uploads may be larger than the usual small-form limit", len(noise) > 256 * 1024 and response.status_code == 200)
        for name, content in (("not an image", b"<svg></svg>"), ("too many pixels on one side", png(Image.new("RGB", (4097, 1)))),
                              ("too many bytes", b"x" * (logos.MAX_BYTES + 1))):
            response = client.post("/api/logos", files={"file": ("logo.png", content, "image/png")}, headers=origin)
            check(f"uploads reject {name}", response.status_code == 400)
        response = client.post("/api/logos", files={"file": ("logo.png", b"x" * (logos.MAX_BYTES + 128 * 1024), "image/png")}, headers=origin)
        check("the request gate also caps logo uploads", response.status_code == 413)
        with patch.object(config, "ACCOUNTS", True):
            check("logos cannot be read without signing in",
                  client.get(f"/api/logos/{logo['id']}").status_code == 401)

        with ctx.as_user(user):
            creator = creators.create({"name": "Logo creator", "logo": logo})
            source = {"type": "file", "name": "Logo test"}
            job = jobs.create(source, {}, enqueue=False, creator=creator["id"])
            live_job = jobs.create(source, {}, enqueue=False, creator=creator["id"], kind="live")
            plain = jobs.create(source, {"logo": None}, enqueue=False, creator=creator["id"])
            check("videos and live jobs inherit creator logos",
                  job["options"]["logo"] == logo and live_job["options"]["logo"] == logo)
            check("video options can explicitly turn a creator's logo off", plain["options"]["logo"] is None)
            check("new creators without logos keep the old appearance", creators.create({"name": "Plain"})["logo"] is None)
            creators._mem.pop(user)
            check("creator logos survive reloading saved settings", creators.get(creator["id"])["logo"] == logo)

            clip = {"id": "clip1", "start": 0.0, "end": 4.0, "status": "done", "hook": "",
                    "title": "A clip", "description": "", "hashtags": [], "score": 95, "captions": False}
            job.update(status="done", source_path=str(Path(data) / "source.mp4"), width=320, height=568,
                       duration=4.0, clips=[clip])
            jobs.save(job)
            with patch.object(render, "_render_in", return_value={"file": "clip1.mp4"}) as encode:
                jobs.render_one(job, clip, [])
                check("older clip records inherit the job's saved logo when rendered",
                      clip["logo"] == logo and encode.call_args.kwargs["logo"] == logo)
                creators.update(creator["id"], {"logo": None})
                check("updating a creator does not change existing clips", clip["logo"] == logo)

            with patch.object(jobs._q, "put") as queue:
                for value in (False, "logo.png", {"id": "../logo"}, dict(logo, width=0), dict(logo, x=101),
                              dict(logo, y=float("nan")), dict(logo, width=True), dict(logo, width="15"),
                              dict(logo, width=10**400)):
                    try:
                        server.rerender(job["id"], clip["id"], {"logo": value})
                    except HTTPException as error:
                        check(f"invalid logo settings are rejected: {value!r}", error.status_code == 400)
                    else:
                        raise AssertionError(f"Accepted invalid settings: {value!r}")
                check("invalid settings neither change the clip nor queue a render",
                      clip["logo"] == logo and clip["status"] == "done" and not queue.called)
                changed = dict(logo, width=30, x=35, y=75)
                server.rerender(job["id"], clip["id"], {"logo": changed})
                saved = json.loads((Path(job["dir"]) / "job.json").read_text())["clips"][0]
                check("individual size and position overrides are saved and queued",
                      saved["logo"] == changed and queue.call_args.args[0] == ("clip", job["id"], clip["id"]))
                with patch.object(render, "_render_in", return_value={"file": "clip1.mp4"}) as encode:
                    jobs.render_one(job, clip, [])
                    check("the renderer receives the individual logo override",
                          clip["status"] == "done" and encode.call_args.kwargs["logo"] == changed)
                server.rerender(job["id"], clip["id"], {"logo": None})
                with patch.object(render, "_render_in", return_value={"file": "clip1.mp4"}) as encode:
                    jobs.render_one(job, clip, [])
                    check("turning off a logo does not silently inherit it again",
                          clip["logo"] is None and encode.call_args.kwargs["logo"] is None)

            creators.update(creator["id"], {"logo": logo})
            settings = creators.get(creator["id"])
            session = live.Session(live_job, settings)
            live_job["clips"] = []
            with patch.object(jobs, "submit_live"):
                session._add_clip(dict(clip, status="queued", start=0, end=4))
                session.settings = dict(settings, logo=changed)
                session._add_clip(dict(clip, status="queued", start=4, end=8))
            check("live clips snapshot current creator settings, including changes while recording",
                  [c["logo"] for c in live_job["clips"]] == [logo, changed])

            tall = logos.upload(png(Image.new("RGB", (10, 100))))
            try:
                creators.update(creator["id"], {"logo": dict(tall, width=100)})
            except ValueError as error:
                check("a size too tall for the frame is rejected before rendering", "too tall" in str(error))
            else:
                raise AssertionError("Accepted a logo that does not fit")

        with ctx.as_user("another-user"):
            try:
                server.logo_image(logo["id"])
            except HTTPException as error:
                check("another user cannot read a logo", error.status_code == 404)
            else:
                raise AssertionError("Another user could read a logo")
            try:
                creators.create({"name": "Other", "logo": logo})
            except ValueError:
                print("PASS another user cannot use a logo in their settings")
            else:
                raise AssertionError("Another user could use a logo")

        source = Path(data) / "source.mp4"
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "color=black:s=320x568:r=30",
                        "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000", "-t", "1", "-c:v", "libx264",
                        "-pix_fmt", "yuv420p", "-c:a", "aac", str(source)], check=True, timeout=30)

        def frame(path, time):
            result = subprocess.run(["ffmpeg", "-v", "error", "-ss", str(time), "-i", str(path), "-frames:v", "1",
                                     "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"], capture_output=True, check=True, timeout=30)
            return Image.frombytes("RGB", (config.OUT_W, config.OUT_H), result.stdout)

        with ctx.as_user(user), patch.object(render, "_qsv_ok", False):
            for name, width, x, y in (("top-left", 20, 0, 0), ("bottom-right", 35, 100, 100), ("custom", 25, 37, 61)):
                options = dict(logo, width=width, x=x, y=y)
                result = render.render_clip(source, Path(data) / "renders", name,
                                            {"start": 0, "end": 0.8, "layout": "crop", "captions": False, "logo": options},
                                            [], 320, 568)
                w = round(config.OUT_W * width / 100)
                h = round(w / 2)
                left = round((config.OUT_W - w) * x / 100)
                top = round((config.OUT_H - h) * y / 100)
                for time in (0.05, 0.65):
                    rendered = frame(Path(data) / "renders" / result["file"], time)
                    solid = rendered.getpixel((left + w // 2, top + h // 2))
                    clear = rendered.getpixel((left + w // 8, top + h // 2))
                    alpha = rendered.getpixel((left + 7 * w // 8, top + h // 2))
                    check(f"{name}: position, aspect ratio and transparency at {time}s",
                          solid[0] > 220 and max(solid[1:]) < 30 and max(clear) < 30
                          and 95 < alpha[0] < 160 and max(alpha[1:]) < 30)
                    outside = rendered.getpixel((left + w + 10 if left + w + 10 < config.OUT_W else left - 10, top + h // 2))
                    check(f"{name}: logo width matches the requested percentage at {time}s", max(outside) < 30)
                with Image.open(Path(data) / "renders" / result["cover"]) as cover:
                    check(f"{name}: the saved cover also includes the logo",
                          cover.size == (config.OUT_W, config.OUT_H) and cover.getpixel((left + w // 2, top + h // 2))[0] > 220)
                check(f"{name}: the image does not shorten or extend the clip",
                      abs(float(subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                                         "-of", "default=noprint_wrappers=1:nokey=1",
                                                         str(Path(data) / "renders" / result["file"])])) - 0.8) < 0.1)
            result = render.render_clip(source, Path(data) / "renders", "off",
                                        {"start": 0, "end": 0.8, "layout": "crop", "captions": False}, [], 320, 568)
            check("clips without a logo still render without one",
                  max(frame(Path(data) / "renders" / result["file"], 0.65).getpixel((100, 100))) < 30)
    finally:
        db.engine.dispose()


if __name__ == "__main__":
    with tempfile.TemporaryDirectory(prefix="pc-logos-") as data:
        main(data)
