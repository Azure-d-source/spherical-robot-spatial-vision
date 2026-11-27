import json
import struct
import sys
import unittest
from argparse import Namespace
from http.client import IncompleteRead
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event
from types import SimpleNamespace
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient
from PIL import Image

from src.api.main import create_app
from src.api.settings import Settings
from src.workers import reconstruct_gaussians as cli
from src.workers import runner, splat_executor
from src.workers.simulation_camera import frame_calibration


PLY = b"""ply
format ascii 1.0
element vertex 1
property float x
property float y
property float z
property float opacity
property float scale_0
property float rot_0
property float f_dc_0
end_header
0 0 0 1 1 1 1
"""


class ReconstructionTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(TemporaryDirectory()))
        self.source = []
        for index in range(4):
            path = self.root / f"{index}.png"
            Image.new("RGB", (4, 4), (index, 0, 0)).save(path)
            self.source.append(path)

    def colmap(self, count, points, has_component=True):
        model = SimpleNamespace(
            num_reg_images=lambda: count, num_points3D=lambda: points,
            reg_image_ids=lambda: range(1, count + 1),
            image=lambda index: SimpleNamespace(name=f"{index:05d}.png"),
            write=Mock(),
        )
        return SimpleNamespace(
            __version__="test", CameraMode=SimpleNamespace(SINGLE=1), Device=SimpleNamespace(cpu=1),
            ImageReaderOptions=Mock(), extract_features=Mock(), match_exhaustive=Mock(),
            incremental_mapping=Mock(return_value={0: model} if has_component else {}),
        )

    def options(self, output):
        return Namespace(
            images=self.source, output_dir=self.root / output, brush_exe=Path(sys.executable),
            splat_transform_cli=None, long_edge=4, steps=400, max_splats=100,
            ssim_weight=None, eval_split_every=None,
        )

    def test_three_of_four_frames_reach_brush_and_manifest(self):
        def brush(command, _log):
            destination = Path(command[command.index("--export-path") + 1])
            (destination / "export_400.ply").write_bytes(PLY)

        with patch.dict(sys.modules, {"pycolmap": self.colmap(3, 5)}):
            with patch.object(cli, "run_tool", side_effect=brush):
                manifest_path = cli.reconstruct(self.options("partial"))
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(manifest["colmap"]["registered_images"], 3)
        self.assertEqual(manifest["colmap"]["total_images"], 4)
        self.assertEqual(manifest["colmap"]["unregistered_frames"][0]["input_index"], 3)
        self.assertFalse(manifest["frames"][3]["registered"])
        self.assertTrue((manifest_path.parent / "scene.ply").is_file())

    def test_insufficient_components_stop_before_brush(self):
        for count, points, has_component in [(0, 0, False), (2, 10, True), (3, 0, True)]:
            with self.subTest(count=count, points=points, has_component=has_component):
                with patch.dict(sys.modules, {"pycolmap": self.colmap(count, points, has_component)}):
                    with patch.object(cli, "run_tool") as brush:
                        with self.assertRaises(cli.RegistrationError) as failed:
                            cli.reconstruct(self.options("failed"))
                        self.assertEqual(failed.exception.unregistered_indices, list(range(count, 4)))
                        brush.assert_not_called()
        self.assertFalse((self.root / "failed").exists())

    def test_virtual_camera_calibration_matches_capture_and_rejects_other_inputs(self):
        frame = {"view_label": "[sim-v1:70,0,-175] rear @cam:180,21,425", "width": 960, "height": 720}
        calibration = frame_calibration(frame)
        self.assertEqual(calibration["target"], (0.7, 1.05, 0))
        self.assertEqual([row[2] for row in calibration["intrinsics"]], [480, 360, 1])
        for point, expected in ((calibration["center"], (0, 0, 0)), (calibration["target"], (0, 0, 4.25))):
            for axis, value in zip(calibration["extrinsics"], expected, strict=False):
                self.assertAlmostEqual(sum(a * b for a, b in zip(axis, (*point, 1), strict=True)), value)
        self.assertIsNone(frame_calibration({**frame, "width": 600}))
        self.assertIsNone(frame_calibration({**frame, "view_label": "[sim-v1:0,0,0] front"}))
        self.assertIsNone(frame_calibration({**frame, "view_label": "[sim-v1:0,0,0] top @cam:180,95,425"}))


class WorkbenchRegistrationTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(TemporaryDirectory()))
        self.enterContext(patch.dict("os.environ", SPATIAL_WORKER_TOKEN="test-token"))
        self.client = self.enterContext(TestClient(create_app(Settings(self.root, self.root / "dist"))))
        self.headers = {"X-Worker-Token": "test-token"}

    def post(self, path, payload, **kwargs):
        response = self.client.post(path, json=payload, **kwargs)
        response.raise_for_status()
        return response.json() if response.status_code != 204 else None

    def create_job(self, frame_count, recipe, kind="splat"):
        scene = self.post("/api/scenes", {"title": recipe, "source": "sample"})
        base = f"/api/scenes/{scene['scene_id']}"
        frames = []
        for index in range(frame_count):
            image = BytesIO()
            Image.new("RGB", (4, 4), (index, 0, 0)).save(image, "PNG")
            response = self.client.post(
                base + "/frames", data={"view_label": "front"},
                files={"image": (f"{index}.png", image.getvalue(), "image/png")},
            )
            response.raise_for_status()
            frames.append(response.json()["frame_id"])
        revision = self.post(base + "/revisions", {"frame_ids": frames})
        job = self.post("/api/jobs", {
            "kind": kind, "revision_id": revision["revision_id"], "recipe_version": recipe,
        })
        return job["job_id"], frames

    def complete(self, job_id, registered, count):
        claim = self.post("/api/internal/workers/claim", {}, headers=self.headers)
        self.assertEqual(claim["job_id"], job_id)
        directory = self.root / "staging" / job_id / f"attempt-{claim['attempt']}" / "out"
        directory.mkdir(parents=True)
        (directory / "scene.ply").write_bytes(PLY)
        manifest = {
            "frames": [{"registered": index < registered} for index in range(count)],
            "colmap": {
                "registered_images": registered, "total_images": count, "sparse_points": 5,
                "unregistered_frames": [{"input_index": index} for index in range(registered, count)],
            },
        }
        (directory / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        path = f"/api/internal/jobs/{job_id}/complete"
        lease = {"lease_token": claim["lease_token"]}
        result = self.post(path, lease, headers=self.headers)
        self.assertEqual(self.post(path, lease, headers=self.headers), result)
        self.assertNotIn("lease_token", result)
        return result

    def test_ordinary_partial_publishes_with_missing_frame_ids(self):
        job_id, frames = self.create_job(4, "v1")
        result = self.complete(job_id, 3, 4)
        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(result["registration"]["unregistered_frame_ids"], [frames[-1]])
        self.assertEqual(self.client.get(f"/api/artifacts/{job_id}/scene.ply").content, PLY)
        response = self.client.get(f"/api/artifacts/{job_id}/manifest.json")
        self.assertEqual(response.json()["registration"], result["registration"])

    def test_strict_recipe_rejects_partial_and_accepts_all(self):
        for registered, status in [(31, "failed"), (32, "succeeded")]:
            with self.subTest(registered=registered):
                job_id, frames = self.create_job(32, "public-32-v1")
                result = self.complete(job_id, registered, 32)
                self.assertEqual(result["status"], status)
                self.assertEqual(result["registration"]["unregistered_frame_ids"], frames[registered:])
                path = f"/api/artifacts/{job_id}/scene.ply"
                if status == "failed":
                    self.assertEqual(result["error_code"], "INCOMPLETE_REGISTRATION")
                    self.assertEqual(result["artifacts"], [])
                    self.assertEqual(self.client.get(path).status_code, 404)
                else:
                    self.assertEqual(self.client.get(path).status_code, 200)

    def test_runner_maps_cli_registration_failure(self):
        job_id, frames = self.create_job(3, "v1")
        claim = self.post("/api/internal/workers/claim", {}, headers=self.headers)
        failed_cli = self.root / "failed_cli.py"
        failed_cli.write_text(
            "import sys\nfrom pathlib import Path\n"
            "assert not Path(sys.argv[2]).exists()\n"
            "print('INSUFFICIENT_REGISTRATION: test', file=sys.stderr)\n"
            "print('UNREGISTERED_INPUT_INDICES: [1, 2]', file=sys.stderr)\n"
            "sys.exit(1)\n", encoding="utf-8",
        )
        args = Namespace(api_url="unused", data_dir=self.root, python=sys.executable,
                         brush="unused", splat_transform=None)
        reports = []

        def post_without_first_response(_url, path, payload):
            self.post("/api/internal/" + path, payload, headers=self.headers)
            reports.append(payload)
            if len(reports) == 1:
                raise IncompleteRead(b"")
            return None

        with patch.object(splat_executor, "SCRIPT", failed_cli):
            with patch.object(runner, "post", side_effect=post_without_first_response):
                self.assertTrue(runner.run_job(args, claim, Event()))
        result = self.client.get(f"/api/jobs/{job_id}").json()
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["error_code"], "INSUFFICIENT_REGISTRATION")
        self.assertEqual(result["error_message"], reports[0]["error_message"])
        self.assertIn("请补拍", result["error_message"])
        self.assertEqual(result["registration"], {
            "registered_images": 1, "total_images": 3, "unregistered_frame_ids": frames[1:],
        })
        self.assertEqual(result["artifacts"], [])
        self.assertEqual(reports, [reports[0], reports[0]])

    def test_fusion_uses_da3_interpreter_and_publishes_frame_previews(self):
        self.create_job(3, "v1")
        job_id, frames = self.create_job(2, "v1", kind="fusion")
        claim = self.post("/api/internal/workers/claim", {"kinds": ["fusion", "splat"]}, headers=self.headers)
        self.assertEqual(claim["job_id"], job_id)

        fake_da3 = self.root / "fake_da3.py"
        payload = json.dumps({
            "accessors": [{"count": 1}], "meshes": [{"primitives": [{"mode": 0, "attributes": {"POSITION": 0}}]}],
        }).encode()
        payload += b" " * (-len(payload) % 4)
        glb = struct.pack("<4sIII4s", b"glTF", 2, len(payload) + 20, len(payload), b"JSON") + payload
        fake_da3.write_text(
            "import json, sys\nfrom pathlib import Path\nfrom PIL import Image\n"
            "out = Path(sys.argv[2])\nassert '--with-depth' in sys.argv and not out.exists()\n"
            "(out / 'depth_vis').mkdir(parents=True)\n"
            f"(out / 'scene.glb').write_bytes({glb!r})\n"
            "frames = []\nfor index in range(2):\n"
            "    preview = f'depth_vis/{index:04d}.jpg'\n"
            "    Image.new('RGB', (8, 4)).save(out / preview)\n"
            "    frames.append({'depth_preview': preview})\n"
            "manifest = {'frames': frames, 'result': {'point_cloud': 'scene.glb', 'point_count': 1}}\n"
            "(out / 'manifest.json').write_text(json.dumps(manifest))\n", encoding="utf-8",
        )
        args = Namespace(api_url="unused", data_dir=self.root, python="unavailable-gs-interpreter",
                         da3_python=sys.executable, da3_model="unused")
        reports = []

        def post_with_connection_reset(_url, path, payload):
            reports.append(payload)
            if len(reports) == 1:
                raise ConnectionResetError("test reconnection")
            return self.post("/api/internal/" + path, payload, headers=self.headers)

        with patch.object(splat_executor, "POINT_SCRIPT", fake_da3):
            with patch.object(runner, "post", side_effect=post_with_connection_reset):
                self.assertTrue(runner.run_job(args, claim, Event()))
        result = self.client.get(f"/api/jobs/{job_id}").json()
        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(reports, [reports[0], reports[0]])
        preview_ids = [a["frame_id"] for a in result["artifacts"] if a["filename"].endswith(".jpg")]
        self.assertEqual(preview_ids, frames)
        for artifact in result["artifacts"]:
            response = self.client.get(artifact["url"])
            self.assertEqual(response.status_code, 200)
            self.assertEqual(len(response.content), artifact["size_bytes"])
