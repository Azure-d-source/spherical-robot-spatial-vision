import sqlite3
import unittest
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from fastapi.testclient import TestClient
from PIL import Image

from src.api.images import MAX_BYTES, MAX_PIXELS, MAX_REQUEST
from src.api.main import create_app
from src.api.settings import Settings


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(TemporaryDirectory()))
        self.dist = self.root / "dist"
        app = create_app(Settings(data_dir=self.root, web_dist=self.dist))
        self.client = self.enterContext(TestClient(app))
        self.scene = self.create_scene("Toy")

    def post_json(self, path, body):
        response = self.client.post(path, json=body)
        response.raise_for_status()
        return response.json()

    def create_scene(self, title):
        scene = self.post_json("/api/scenes", {"title": title, "source": "sample"})
        return f"/api/scenes/{scene['scene_id']}"

    def upload(self, capture_id, color, scene=None):
        image = BytesIO()
        Image.new("RGB", (4, 4), color).save(image, "PNG")
        return self.upload_bytes(image.getvalue(), capture_id, scene)

    def upload_bytes(self, data, capture_id="camera", scene=None):
        return self.client.post(
            (scene or self.scene) + "/frames",
            data={"capture_id": capture_id, "view_label": "front"},
            files={"image": ("toy.png", data, "image/png")},
        )

    def test_upload_size_limits_with_and_without_content_length(self):
        sized = self.upload_bytes(b"x" * (MAX_BYTES + 1))
        self.assertEqual(sized.status_code, 413)
        headers = {"Content-Type": "multipart/form-data; boundary=upload"}
        prefix = b'--upload\r\nContent-Disposition: form-data; name="image"; filename="toy.png"\r\n\r\n'
        chunk = b"x" * (1024 * 1024)

        def body():
            yield prefix
            for _ in range(MAX_REQUEST // len(chunk) + 1):
                yield chunk
            yield b"\r\n--upload--\r\n"

        for content in (b"".join(body()), body()):
            with self.subTest(streamed=not isinstance(content, bytes)):
                response = self.client.post(self.scene + "/frames", headers=headers, content=content)
                if not isinstance(content, bytes):
                    self.assertNotIn("content-length", response.request.headers)
                self.assertEqual(response.status_code, 413)
        self.assertEqual(self.client.get(self.scene + "/frames").json(), [])
        self.assertEqual(list((self.root / "photos").iterdir()), [])

    def test_upload_rejects_corrupt_animated_and_oversized_images(self):
        animation = BytesIO()
        Image.new("RGB", (4, 4), "blue").save(
            animation, "PNG", save_all=True, append_images=[Image.new("RGB", (4, 4), "red")]
        )
        large = BytesIO()
        width = 6000
        Image.new("1", (width, MAX_PIXELS // width + 1)).save(large, "PNG")
        for name, payload, status in (
            ("corrupt", b"\x89PNG\r\n\x1a\n", 422),
            ("animated", animation.getvalue(), 422),
            ("oversized", large.getvalue(), 413),
        ):
            with self.subTest(name=name):
                self.assertEqual(self.upload_bytes(payload).status_code, status)
        self.assertEqual(self.client.get(self.scene + "/frames").json(), [])

    def test_failed_commit_removes_only_new_photo_and_allows_retry(self):
        saved = self.upload("existing", "blue").json()
        next_scene = self.create_scene("Second scene")
        photos = self.root / "photos"
        existing_files = set(photos.iterdir())
        connect = sqlite3.connect

        class FailingCommit(sqlite3.Connection):
            def commit(self):
                if self.total_changes:
                    raise sqlite3.OperationalError("simulated commit failure")
                super().commit()

        with patch("src.api.store.sqlite3.connect", side_effect=lambda *args, **kwargs: connect(
            *args, **kwargs, factory=FailingCommit
        )):
            with self.assertRaisesRegex(sqlite3.OperationalError, "simulated commit failure"):
                self.upload("new", "red")
            with self.assertRaisesRegex(sqlite3.OperationalError, "simulated commit failure"):
                self.upload("same-bytes", "blue", scene=next_scene)

        self.assertEqual(set(photos.iterdir()), existing_files)
        self.assertEqual(self.client.get(saved["image_url"]).status_code, 200)
        self.assertEqual(self.client.get(self.scene + "/frames").json(), [saved])
        self.assertEqual(self.client.get(next_scene + "/frames").json(), [])
        self.assertEqual(self.upload("new", "red").status_code, 201)

    def test_workbench_can_be_built_after_api_start(self):
        self.assertEqual(self.client.get("/api/health").status_code, 200)
        self.assertEqual(self.client.get("/").status_code, 404)
        self.dist.mkdir()
        (self.dist / "index.html").write_text("<h1>Workbench</h1>", encoding="utf-8")
        self.assertEqual(self.client.get("/").text, "<h1>Workbench</h1>")
        self.assertEqual(self.client.get("/api/health").status_code, 200)

    def test_workbench_serves_supersplat_decoder_with_wasm_mime(self):
        directory = self.dist / "supersplat"
        directory.mkdir(parents=True)
        (self.dist / "index.html").write_text("<h1>Workbench</h1>", encoding="utf-8")
        wasm = b"\x00asm\x01\x00\x00\x00"
        (directory / "zstd-decoder.wasm").write_bytes(wasm)
        response = self.client.get("/supersplat/zstd-decoder.wasm")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "application/wasm")
        self.assertEqual(response.content, wasm)
        partial = self.client.get("/supersplat/zstd-decoder.wasm", headers={"Range": "bytes=0-3"})
        self.assertEqual(partial.status_code, 206)
        self.assertEqual(partial.headers["content-type"], "application/wasm")
        self.assertEqual(partial.content, wasm[:4])

    def test_upload_retries_preserve_capture_identity(self):
        original = self.upload("camera-1", "blue")
        original.raise_for_status()
        for capture_id in ["camera-1", "camera-alias"]:
            with self.subTest(capture_id=capture_id):
                retry = self.upload(capture_id, "blue")
                retry.raise_for_status()
                self.assertEqual(retry.json()["frame_id"], original.json()["frame_id"])
                self.assertEqual(self.upload(capture_id, "red").status_code, 409)
        self.assertEqual(self.client.get(self.scene + "/frames").json(), [original.json()])

    def test_revision_history_and_job_identity(self):
        revisions_url = self.scene + "/revisions"
        front = self.upload("front", "blue").json()["frame_id"]
        first = self.post_json(revisions_url, {"frame_ids": [front]})
        back = self.upload("back", "red").json()["frame_id"]
        order = {"frame_ids": [back, front]}
        second = self.post_json(revisions_url, order)
        self.assertEqual(self.post_json(revisions_url, order), second)
        history = {row["version"]: row for row in self.client.get(revisions_url).json()}
        self.assertEqual(len(history), 2)
        self.assertEqual(history[first["version"]]["frame_ids"], [front])
        self.assertEqual(history[second["version"]]["frame_ids"], [back, front])

        other = self.create_scene("Independent scene")
        invalid = self.client.post(other + "/revisions", json=order)
        self.assertEqual(invalid.status_code, 422)
        self.assertEqual(self.client.get(other + "/revisions").json(), [])

        request = {"revision_id": second["revision_id"], "kind": "fusion", "recipe_version": "v1"}
        job = self.post_json("/api/jobs", request)
        self.assertEqual(self.post_json("/api/jobs", request)["job_id"], job["job_id"])
        self.assertEqual(job["revision_id"], second["revision_id"])
        self.assertEqual(job["status"], "queued")
        self.assertEqual(self.client.get(self.scene + "/jobs").json(), [job])


if __name__ == "__main__":
    unittest.main()
