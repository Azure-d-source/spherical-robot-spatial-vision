import unittest
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from fastapi.testclient import TestClient
from PIL import Image

from src.api import store
from src.api.main import app


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        root = Path(self.enterContext(TemporaryDirectory()))
        self.enterContext(patch.object(store, "DATABASE", root / "workspace.sqlite3"))
        self.enterContext(patch.object(store, "PHOTOS", root / "photos"))
        self.client = self.enterContext(TestClient(app))
        self.scene = self.create_scene("Toy")

    def post_json(self, path, body):
        response = self.client.post(path, json=body)
        response.raise_for_status()
        return response.json()

    def create_scene(self, title):
        scene = self.post_json("/api/scenes", {"title": title, "source": "sample"})
        return f"/api/scenes/{scene['scene_id']}"

    def upload(self, capture_id, color):
        image = BytesIO()
        Image.new("RGB", (4, 4), color).save(image, "PNG")
        return self.client.post(
            self.scene + "/frames",
            data={"capture_id": capture_id, "view_label": "front"},
            files={"image": ("toy.png", image.getvalue(), "image/png")},
        )

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
