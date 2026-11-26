import json
import os
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Barrier, Event
from unittest.mock import patch
from uuid import uuid4

from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import create_engine, select, update
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateSchema, DropSchema

from src.api.images import MAX_BYTES, MAX_REQUEST, read_image
from src.api.platform.accounts import Account, COOKIE, LoginSession, Team, password_hasher, session_hash
from src.api.platform.app import create_app
from src.api.platform.config import PlatformSettings
from src.api.platform.jobs import JobRun

DB_URL = os.environ.get("SPATIAL_TEST_DATABASE_URL")
MIGRATIONS = Path(__file__).resolve().parents[1] / "src/api/platform/alembic.ini"
ORIGIN = "https://workbench.example.test"
WORKER_HEADERS = {"X-Worker-Token": "private-test-worker"}


@unittest.skipUnless(DB_URL, "SPATIAL_TEST_DATABASE_URL is required for PostgreSQL integration tests")
class PlatformApiTests(unittest.TestCase):
    def setUp(self):
        schema = f"orbit_test_{uuid4().hex}"
        admin = create_engine(DB_URL)
        self.addCleanup(admin.dispose)
        with admin.begin() as connection:
            connection.execute(CreateSchema(schema))

        def drop_schema():
            with admin.begin() as connection:
                connection.execute(DropSchema(schema, cascade=True))

        self.addCleanup(drop_schema)
        dsn = make_url(DB_URL).update_query_dict({"options": f"-csearch_path={schema}"})
        photos_dir = Path(self.enterContext(TemporaryDirectory()))
        self.settings = PlatformSettings(dsn.render_as_string(hide_password=False), ORIGIN, photos_dir,
                                         worker_token=WORKER_HEADERS["X-Worker-Token"])
        self.enterContext(patch.dict(os.environ, SPATIAL_DATABASE_URL=self.settings.database_url))
        command.upgrade(Config(str(MIGRATIONS)), "head")
        self.engine = create_engine(dsn)
        self.addCleanup(self.engine.dispose)

        self.owner = uuid4().hex
        self.member = uuid4().hex
        self.team = uuid4().hex
        other_team = uuid4().hex
        self.password = uuid4().hex
        credential = password_hasher.hash(self.password)
        with Session(self.engine) as db:
            db.add_all([Team(team_id=self.team, slug="team"), Team(team_id=other_team, slug="other")])
            db.flush()
            db.add_all([
                Account(account_id=self.owner, email="owner@example.test", team_id=self.team,
                        role="admin", password_hash=credential),
                Account(account_id=self.member, email="member@example.test", team_id=self.team,
                        role="member", password_hash=credential),
                Account(account_id=uuid4().hex, email="colleague@example.test", team_id=self.team,
                        role="member", password_hash=credential),
                Account(account_id=uuid4().hex, email="outsider@example.test", team_id=other_team,
                        role="member", password_hash=credential),
            ])
            db.commit()

    def logged_in(self, client, email):
        response = client.post("/api/auth/login", json={"email": email, "password": self.password},
                               headers={"Origin": ORIGIN})
        self.assertEqual(response.status_code, 200, response.text)
        return response

    def test_members_share_scenes_and_outside_team_cannot_see_them(self):
        app = create_app(self.settings)
        with TestClient(app, base_url=ORIGIN) as owner:
            self.assertEqual(owner.get("/api/scenes").json()["code"], "LOGIN_REQUIRED")
            self.logged_in(owner, " OWNER@example.test ")
            created = owner.post("/api/scenes", json={"title": "书桌", "source": "sample"})
            self.assertEqual(created.status_code, 201)
            record = created.json()
            self.assertEqual((record["team_id"], record["owner_id"]), (self.team, self.owner))
            self.assertEqual(owner.post("/api/scenes", json={**record, "title": "invalid"}).status_code, 422)
        # Restart the service with the same database and log in as the other accounts.
        with TestClient(create_app(self.settings), base_url=ORIGIN) as member:
            self.logged_in(member, "member@example.test")
            self.assertEqual(member.get("/api/scenes").json(), [record])
            self.assertEqual(member.get(f"/api/scenes/{record['scene_id']}").json(), record)
        with TestClient(create_app(self.settings), base_url=ORIGIN) as outsider:
            self.logged_in(outsider, "outsider@example.test")
            self.assertEqual(outsider.get("/api/scenes").json(), [])
            result = outsider.get(f"/api/scenes/{record['scene_id']}")
            self.assertEqual((result.status_code, result.json()["code"]), (404, "SCENE_NOT_FOUND"))

    def test_sessions_are_secure_expiring_and_revocable(self):
        with TestClient(create_app(self.settings), base_url=ORIGIN) as client:
            denied = client.post("/api/auth/login", json={"email": "owner@example.test", "password": "incorrect"})
            self.assertEqual((denied.status_code, denied.json()["code"]), (401, "INVALID_CREDENTIALS"))
            invalid = client.post("/api/auth/login", json={"email": "owner@example.test", "password": "a" * 257})
            self.assertEqual(invalid.status_code, 422)
            self.assertNotIn("a" * 257, invalid.text)
            response = self.logged_in(client, "owner@example.test")
            self.assertNotIn("password_hash", response.json())
            cookie = response.headers["set-cookie"]
            self.assertIn("HttpOnly", cookie)
            self.assertIn("Secure", cookie)
            self.assertIn("SameSite=strict", cookie)
            token = client.cookies.get(COOKIE)
            with Session(self.engine) as db:
                self.assertEqual(db.scalar(select(LoginSession.session_hash)), session_hash(token))
            self.assertEqual(client.get("/api/auth/me").json()["account_id"], self.owner)
            self.assertEqual(client.post("/api/auth/logout").status_code, 204)
            self.assertEqual(client.get("/api/auth/me", headers={"Cookie": f"{COOKIE}={token}"}).status_code, 401)
            self.logged_in(client, "owner@example.test")
            with Session(self.engine) as db:
                db.execute(update(LoginSession).values(expires_at=datetime.now(timezone.utc) - timedelta(seconds=1)))
                db.commit()
            self.assertEqual(client.get("/api/auth/me").status_code, 401)

    def test_same_origin_writes_and_migration_match_schema(self):
        command.check(Config(str(MIGRATIONS)))
        with TestClient(create_app(self.settings), base_url=ORIGIN) as client:
            self.logged_in(client, "owner@example.test")
            response = client.post("/api/scenes", json={"title": "test", "source": "sample"},
                                   headers={"Origin": "https://another.example.test"})
            self.assertEqual((response.status_code, response.json()["code"]), (403, "ORIGIN_FORBIDDEN"))
            self.assertEqual(client.get("/api/scenes").json(), [])
            self.assertEqual(client.get("/api/health").json(), {"status": "ok"})

    def photo(self, color="blue"):
        output = BytesIO()
        Image.new("RGB", (4, 4), color).save(output, "PNG")
        return output.getvalue()

    def create_scene(self, client):
        response = client.post("/api/scenes", json={"title": "共享采集", "source": "sample"})
        self.assertEqual(response.status_code, 201, response.text)
        return f"/api/scenes/{response.json()['scene_id']}"

    def upload(self, client, scene, data, capture_id="shot", **metadata):
        return client.post(scene + "/frames", data={"capture_id": capture_id, **metadata},
                           files={"image": ("scene.png", data, "image/png")})

    def test_concurrent_duplicates_share_photo_and_record_both_members(self):
        app = create_app(self.settings)
        with TestClient(app, base_url=ORIGIN) as owner:
            member = TestClient(app, base_url=ORIGIN)
            self.addCleanup(member.close)
            self.logged_in(owner, "owner@example.test")
            member_id = self.logged_in(member, "member@example.test").json()["account_id"]
            scene = self.create_scene(owner)
            raw = self.photo()
            ready = Barrier(2, timeout=8)

            def shoot(client, label):
                ready.wait()
                return self.upload(client, scene, raw, view_label=label)

            with ThreadPoolExecutor(max_workers=2) as pool:
                requests = [pool.submit(shoot, owner, "正面"), pool.submit(shoot, member, "侧面")]
                results = [future.result(timeout=15) for future in requests]
            self.assertEqual(sorted(result.status_code for result in results), [200, 201])
            frame = results[0].json()
            self.assertEqual(frame, results[1].json())
            self.assertEqual(member.get(scene + "/frames").json(), [frame])

            history_url = scene + f"/frames/{frame['frame_id']}/uploads"
            history = owner.get(history_url).json()
            self.assertEqual(
                {(item["uploader_id"], item["capture_id"], item["view_label"]) for item in history},
                {(self.owner, "shot", "正面"), (member_id, "shot", "侧面")},
            )
            retry = self.upload(member, scene, raw, view_label="不同的重试标签")
            self.assertEqual((retry.status_code, retry.json()), (200, frame))
            conflict = self.upload(member, scene, self.photo("red"))
            self.assertEqual((conflict.status_code, conflict.json()["code"]), (409, "CAPTURE_CONFLICT"))
            self.assertEqual(member.get(history_url).json(), history)
            self.assertEqual(len(list(app.state.photos.iterdir())), 1)
            image = member.get(frame["image_url"])
            self.assertEqual((image.status_code, image.content), (200, raw))
            self.assertEqual(image.headers["content-type"], "image/png")

    def test_identical_files_do_not_grant_access_across_teams(self):
        app = create_app(self.settings)
        with TestClient(app, base_url=ORIGIN) as owner:
            self.logged_in(owner, "owner@example.test")
            scene = self.create_scene(owner)
            raw = self.photo()
            first = self.upload(owner, scene, raw)
            self.assertEqual(first.status_code, 201)
            frame = first.json()
            self.assertEqual(frame["view_label"], "未标注")

            outside = TestClient(app, base_url=ORIGIN)
            self.addCleanup(outside.close)
            self.assertEqual(outside.get(frame["image_url"]).status_code, 401)
            self.logged_in(outside, "outsider@example.test")
            self.assertEqual(outside.get(scene + "/frames").status_code, 404)
            self.assertEqual(self.upload(outside, scene, raw).status_code, 404)
            self.assertEqual(outside.get(frame["image_url"]).status_code, 404)
            self.assertEqual(outside.get(scene + f"/frames/{frame['frame_id']}/uploads").status_code, 404)
            other = self.create_scene(outside)
            other_upload = self.upload(outside, other, raw)
            self.assertEqual(other_upload.status_code, 201)
            self.assertNotEqual(other_upload.json()["frame_id"], frame["frame_id"])
            self.assertEqual(outside.get(other_upload.json()["image_url"]).content, raw)
            self.assertEqual(outside.get(frame["image_url"]).status_code, 404)
            self.assertEqual(len(list(app.state.photos.iterdir())), 1)

    def test_invalid_upload_and_failed_commit_leave_no_photo_or_history(self):
        app = create_app(self.settings)
        with TestClient(app, base_url=ORIGIN, raise_server_exceptions=False) as client:
            self.logged_in(client, "owner@example.test")
            scene = self.create_scene(client)
            for data, expected_status, expected_code in (
                (b"bad image", 422, "INVALID_IMAGE"),
                (b"x" * (MAX_BYTES + 1), 413, "PHOTO_LIMIT_EXCEEDED"),
                (b"x" * (MAX_REQUEST + 1), 413, "PHOTO_LIMIT_EXCEEDED"),
            ):
                result = self.upload(client, scene, data)
                self.assertEqual((result.status_code, result.json()["code"]), (expected_status, expected_code))
            with patch.object(Session, "commit", side_effect=SQLAlchemyError("injected commit failure")):
                self.assertEqual(self.upload(client, scene, self.photo()).status_code, 500)
            self.assertEqual(client.get(scene + "/frames").json(), [])
            self.assertEqual(list(app.state.photos.iterdir()), [])
            accepted = self.upload(client, scene, self.photo())
            self.assertEqual(accepted.status_code, 201)
            history = client.get(scene + f"/frames/{accepted.json()['frame_id']}/uploads").json()
            self.assertEqual(len(history), 1)

    def test_frozen_batches_keep_order_identity_and_originals(self):
        app = create_app(self.settings)
        with TestClient(app, base_url=ORIGIN) as owner:
            self.logged_in(owner, "owner@example.test")
            member = TestClient(app, base_url=ORIGIN)
            self.addCleanup(member.close)
            self.logged_in(member, "member@example.test")
            scene = self.create_scene(owner)
            frames = [self.upload(member, scene, self.photo(color), color).json() for color in ("red", "blue")]
            selected = [item["frame_id"] for item in reversed(frames)]
            path = scene + "/revisions"
            created = member.post(path, json={"frame_ids": selected})
            self.assertEqual(created.status_code, 201, created.text)
            revision = created.json()
            self.assertEqual((revision["version"], revision["creator_id"], revision["frame_ids"]),
                             (1, self.member, selected))
            repeat = owner.post(path, json={"frame_ids": selected})
            self.assertEqual((repeat.status_code, repeat.json()), (200, revision))
            reordered = owner.post(path, json={"frame_ids": selected[::-1]})
            self.assertEqual(reordered.status_code, 201)
            self.assertEqual(reordered.json()["version"], 2)
            self.assertEqual(owner.get(path).json(), [reordered.json(), revision])
            self.assertEqual(owner.get(path + "/" + revision["revision_id"]).json(), revision)

            other_scene = self.create_scene(owner)
            foreign_id = self.upload(owner, other_scene, self.photo(), "other").json()["frame_id"]
            bad = owner.post(path, json={"frame_ids": [selected[0], foreign_id]})
            self.assertEqual((bad.status_code, bad.json()["code"]), (422, "FRAME_OUTSIDE_SCENE"))
            repeated = owner.post(path, json={"frame_ids": [selected[0], selected[0]]})
            self.assertEqual((repeated.status_code, repeated.json()["code"]), (422, "INVALID_FRAME_IDS"))
            obsolete = owner.post(path, json={"frame_ids": ["0" * 32]})
            self.assertEqual(obsolete.status_code, 422)
            mixed = self.create_scene(owner)
            mixed_frames = [
                self.upload(owner, mixed, self.photo(color), color, view_label=label).json()["frame_id"]
                for color, label in (("red", "[sim-v1:0,0,0] 正面"), ("blue", "[sim-v1:20,0,0] 正面"))
            ]
            mixed_reply = owner.post(mixed + "/revisions", json={"frame_ids": mixed_frames})
            self.assertEqual((mixed_reply.status_code, mixed_reply.json()["code"]), (422, "MIXED_LAYOUTS"))

            used = member.delete(scene + "/frames/" + selected[0])
            self.assertEqual((used.status_code, used.json()["code"]), (409, "FRAME_IN_USE"))
            self.assertEqual(owner.get(frames[1]["image_url"]).content, self.photo())
            self.assertEqual(owner.get(path + "/" + revision["revision_id"]).json(), revision)

            outsider = TestClient(app, base_url=ORIGIN)
            self.addCleanup(outsider.close)
            self.logged_in(outsider, "outsider@example.test")
            self.assertEqual(outsider.get(path).status_code, 404)
            self.assertEqual(outsider.get(path + "/" + revision["revision_id"]).status_code, 404)
            self.assertEqual(outsider.delete(scene + "/frames/" + selected[0]).status_code, 404)

    def test_only_first_uploader_owner_or_admin_can_withdraw(self):
        app = create_app(self.settings)
        with TestClient(app, base_url=ORIGIN) as admin:
            self.logged_in(admin, "owner@example.test")
            member = TestClient(app, base_url=ORIGIN)
            colleague = TestClient(app, base_url=ORIGIN)
            self.addCleanup(member.close)
            self.addCleanup(colleague.close)
            self.logged_in(member, "member@example.test")
            self.logged_in(colleague, "colleague@example.test")
            scene = self.create_scene(admin)
            raw = self.photo()
            frame = self.upload(member, scene, raw).json()
            self.assertEqual(self.upload(colleague, scene, raw).status_code, 200)
            path = scene + "/frames/" + frame["frame_id"]
            forbidden = colleague.delete(path)
            self.assertEqual((forbidden.status_code, forbidden.json()["code"]), (403, "FRAME_WITHDRAW_FORBIDDEN"))
            self.assertEqual(member.delete(path).status_code, 204)
            self.assertEqual(member.delete(path).status_code, 204)
            self.assertEqual(admin.get(scene + "/frames").json(), [])
            self.assertEqual(admin.get(frame["image_url"]).status_code, 404)
            self.assertEqual(len(admin.get(path + "/uploads").json()), 2)
            blocked = admin.post(scene + "/revisions", json={"frame_ids": [frame["frame_id"]]})
            self.assertEqual((blocked.status_code, blocked.json()["code"]), (409, "FRAME_WITHDRAWN"))

            old = self.upload(member, scene, raw)
            self.assertEqual((old.status_code, old.json()["status"], old.json()["withdrawn_by"]),
                             (200, "withdrawn", self.member))
            self.assertEqual(old.json()["frame_id"], frame["frame_id"])
            accepted = self.upload(member, scene, raw, "new")
            self.assertEqual((accepted.status_code, accepted.json()["status"]), (201, "active"))
            self.assertNotEqual(accepted.json()["frame_id"], frame["frame_id"])
            self.assertEqual(admin.get(scene + "/frames").json(), [accepted.json()])
            self.assertEqual(len(list(app.state.photos.iterdir())), 1)
            self.assertEqual(admin.delete(scene + "/frames/" + accepted.json()["frame_id"]).status_code, 204)

            member_owned = self.create_scene(member)
            other_frame = self.upload(colleague, member_owned, raw).json()
            self.assertEqual(member.delete(member_owned + "/frames/" + other_frame["frame_id"]).status_code, 204)

    def test_freeze_and_withdraw_cannot_both_succeed(self):
        app = create_app(self.settings)
        with TestClient(app, base_url=ORIGIN) as owner:
            self.logged_in(owner, "owner@example.test")
            member = TestClient(app, base_url=ORIGIN)
            self.addCleanup(member.close)
            self.logged_in(member, "member@example.test")
            scene = self.create_scene(owner)
            frame = self.upload(member, scene, self.photo()).json()
            frame_id = frame["frame_id"]
            ready = Barrier(2, timeout=8)

            def freeze():
                ready.wait()
                return owner.post(scene + "/revisions", json={"frame_ids": [frame_id]})

            def withdraw():
                ready.wait()
                return member.delete(scene + "/frames/" + frame_id)

            with ThreadPoolExecutor(max_workers=2) as pool:
                freezing, withdrawing = pool.submit(freeze), pool.submit(withdraw)
                frozen, withdrawn = freezing.result(timeout=15), withdrawing.result(timeout=15)
            if frozen.status_code == 201:
                self.assertEqual((withdrawn.status_code, withdrawn.json()["code"]), (409, "FRAME_IN_USE"))
                self.assertEqual(owner.get(scene + "/revisions").json()[0]["frame_ids"], [frame_id])
                self.assertEqual(member.get(frame["image_url"]).status_code, 200)
            else:
                self.assertEqual(withdrawn.status_code, 204)
                self.assertEqual((frozen.status_code, frozen.json()["code"]), (409, "FRAME_WITHDRAWN"))
                self.assertEqual(owner.get(scene + "/revisions").json(), [])
                self.assertEqual(owner.get(scene + "/frames").json(), [])

    def frozen_fixture(self, client, count=3):
        scene = self.create_scene(client)
        ids = [
            self.upload(client, scene, self.photo((index * 50, 1, 2)), str(index)).json()["frame_id"]
            for index in reversed(range(count))
        ]
        response = client.post(scene + "/revisions", json={"frame_ids": ids})
        self.assertEqual(response.status_code, 201, response.text)
        return scene, response.json()

    def claim(self, client, *, kind="splat"):
        response = client.post("/api/internal/workers/claim", json={"kinds": [kind]}, headers=WORKER_HEADERS)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def splat_output(self, claim):
        output = self.settings.data_dir / "staging" / claim["job_id"] / f"attempt-{claim['attempt']}" / "out"
        output.mkdir(parents=True)
        (output / "scene.ply").write_bytes(b"ply\nformat ascii 1.0\nelement vertex 1\nend_header\n")
        count = len(claim["frames"])
        (output / "manifest.json").write_text(json.dumps({
            "frames": [{"registered": True} for _ in claim["frames"]],
            "colmap": {
                "registered_images": count, "total_images": count, "sparse_points": 5,
                "unregistered_frames": [],
            },
        }), encoding="utf-8")

    def complete_job(self, client, claim, *, kind="succeeded"):
        path = f"/api/internal/jobs/{claim['job_id']}/complete"
        body = {"lease_token": claim["lease_token"]}
        response = client.post(path, json=body, headers=WORKER_HEADERS)
        self.assertEqual(response.status_code, 200, response.text)
        job = response.json()
        self.assertEqual(job["status"], kind)
        self.assertEqual(client.post(path, json=body, headers=WORKER_HEADERS).json(), job)
        return job

    def test_latest_success_survives_failed_and_late_reruns(self):
        app = create_app(self.settings)
        with TestClient(app, base_url=ORIGIN) as user:
            self.logged_in(user, "owner@example.test")
            scene, revision = self.frozen_fixture(user)
            payload = {"revision_id": revision["revision_id"], "kind": "splat"}
            submitted = user.post("/api/jobs", json=payload)
            self.assertEqual(submitted.status_code, 202, submitted.text)
            original = submitted.json()
            self.assertEqual(user.post("/api/jobs", json=payload).json(), original)
            self.assertEqual(user.post("/api/internal/workers/claim", json={}).status_code, 401)

            worker = TestClient(app, base_url="http://127.0.0.1:8001")
            self.addCleanup(worker.close)
            worker_run = self.claim(worker)
            self.assertEqual(worker_run["job_id"], original["job_id"])
            self.assertEqual([frame["frame_id"] for frame in worker_run["frames"]], revision["frame_ids"])
            self.splat_output(worker_run)
            old = self.complete_job(worker, worker_run)
            result_url = scene + "/revisions/" + revision["revision_id"] + "/results"
            self.assertEqual(user.get(result_url).json()["splat"], old)

            rerun_url = "/api/jobs/" + old["job_id"] + "/rerun"
            key_headers = {"Idempotency-Key": "member-command-1"}
            member = TestClient(app, base_url=ORIGIN)
            self.addCleanup(member.close)
            self.logged_in(member, "member@example.test")
            second = member.post(rerun_url, headers=key_headers).json()
            self.assertEqual((second["run_number"], second["submitter_id"], second["rerun_of_id"]),
                             (2, self.member, old["job_id"]))
            self.assertEqual(member.post(rerun_url, headers=key_headers).json()["job_id"], second["job_id"])
            conflict = member.post(f"/api/jobs/{second['job_id']}/rerun", headers=key_headers)
            self.assertEqual((conflict.status_code, conflict.json()["code"]), (409, "RERUN_KEY_CONFLICT"))
            self.assertEqual(member.get(result_url).json()["splat"], old)
            failed_claim = self.claim(worker)
            self.assertEqual(failed_claim["job_id"], second["job_id"])
            self.assertEqual(member.get(result_url).json()["splat"], old)
            failed = self.complete_job(worker, failed_claim, kind="failed")
            self.assertEqual(failed["error_code"], "INVALID_ARTIFACT")
            self.assertEqual(member.get(result_url).json()["splat"], old)

            jobs = [member.post(rerun_url, headers={"Idempotency-Key": f"member-command-{number}"}).json()
                    for number in (2, 3)]
            claims = [self.claim(worker), self.claim(worker)]
            self.assertEqual([c["job_id"] for c in claims], [job["job_id"] for job in jobs])
            for claim in claims:
                self.splat_output(claim)
            newest = self.complete_job(worker, claims[1])
            self.complete_job(worker, claims[0])
            self.assertEqual(member.get(result_url).json()["splat"], newest)
            self.assertEqual(len(member.get(scene + "/jobs").json()), 4)
            self.assertEqual(member.get(old["artifacts"][0]["url"]).status_code, 200)
            manifest = member.get(f"/api/artifacts/{old['job_id']}/manifest.json").json()
            self.assertEqual([frame["frame_id"] for frame in manifest["frames"]], revision["frame_ids"])

            reversed_run = user.post(scene + "/revisions", json={"frame_ids": revision["frame_ids"][::-1]}).json()
            other_batch = f"{scene}/revisions/{reversed_run['revision_id']}/results"
            self.assertIsNone(member.get(other_batch).json()["splat"])
            outside = TestClient(app, base_url=ORIGIN)
            self.addCleanup(outside.close)
            self.logged_in(outside, "outsider@example.test")
            self.assertEqual(outside.get(old["artifacts"][0]["url"]).status_code, 404)
            self.assertEqual(outside.get(result_url).status_code, 404)
            self.assertEqual(outside.post(rerun_url, headers=key_headers).status_code, 404)

    def test_lease_reclaim_ignores_stale_worker_and_does_not_duplicate_claims(self):
        app = create_app(self.settings)
        with TestClient(app, base_url=ORIGIN) as user:
            self.logged_in(user, "owner@example.test")
            _, revision = self.frozen_fixture(user, count=2)
            bad = user.post("/api/jobs", json={"revision_id": revision["revision_id"], "kind": "splat"})
            self.assertEqual((bad.status_code, bad.json()["code"]), (422, "FRAME_COUNT_MISMATCH"))
            created = user.post("/api/jobs", json={"revision_id": revision["revision_id"], "kind": "fusion"}).json()
            clients = [TestClient(app, base_url=ORIGIN) for _ in range(2)]
            for client in clients:
                self.addCleanup(client.close)
            barrier = Barrier(2, timeout=8)

            def request_work(client):
                barrier.wait()
                return client.post("/api/internal/workers/claim", json={"kinds": ["fusion"]}, headers=WORKER_HEADERS)

            with ThreadPoolExecutor(max_workers=2) as pool:
                replies = list(pool.map(request_work, clients))
            self.assertEqual(sorted(reply.status_code for reply in replies), [200, 204])
            first = next(reply.json() for reply in replies if reply.status_code == 200)
            path = f"/api/internal/jobs/{first['job_id']}"
            self.assertEqual(first["job_id"], created["job_id"])
            self.assertEqual(user.post(path + "/heartbeat", json={"lease_token": first["lease_token"]},
                                       headers=WORKER_HEADERS).status_code, 204)
            with Session(self.engine) as db:
                db.execute(update(JobRun).where(JobRun.job_id == first["job_id"]).values(
                    lease_until=datetime.now(timezone.utc) - timedelta(seconds=1),
                ))
                db.commit()

            next_claim = self.claim(user, kind="fusion")
            self.assertEqual((next_claim["job_id"], next_claim["attempt"]), (created["job_id"], 2))
            self.assertNotEqual(next_claim["lease_token"], first["lease_token"])
            stale = user.post(path + "/complete", json={"lease_token": first["lease_token"]},
                              headers=WORKER_HEADERS)
            self.assertEqual((stale.status_code, stale.json()["code"]), (409, "LEASE_LOST"))
            terminal = {"lease_token": next_claim["lease_token"], "error_code": "EXECUTOR_ERROR"}
            self.assertEqual(user.post(path + "/fail", json=terminal, headers=WORKER_HEADERS).status_code, 204)
            self.assertEqual(user.post(path + "/fail", json=terminal, headers=WORKER_HEADERS).status_code, 204)
            self.assertEqual(user.get("/api/jobs/" + created["job_id"]).json()["status"], "failed")

    def test_archived_scene_remains_readable_and_existing_jobs_keep_running(self):
        app = create_app(self.settings)
        with TestClient(app, base_url=ORIGIN) as admin:
            self.logged_in(admin, "owner@example.test")
            member = TestClient(app, base_url=ORIGIN)
            colleague = TestClient(app, base_url=ORIGIN)
            self.addCleanup(member.close)
            self.addCleanup(colleague.close)
            self.logged_in(member, "member@example.test")
            self.logged_in(colleague, "colleague@example.test")

            scene, revision = self.frozen_fixture(member)
            self.assertEqual(colleague.patch(scene, json={"title": "无权限"}).status_code, 403)
            self.assertEqual(colleague.post(scene + "/archive").status_code, 403)
            renamed = member.patch(scene, json={"title": "归档前改名"})
            self.assertEqual((renamed.status_code, renamed.json()["title"]), (200, "归档前改名"))

            payload = {"revision_id": revision["revision_id"], "kind": "splat"}
            first = member.post("/api/jobs", json=payload).json()
            original = self.claim(admin)
            self.splat_output(original)
            old = self.complete_job(admin, original)
            self.assertEqual(first["job_id"], old["job_id"])
            rerun_url = f"/api/jobs/{old['job_id']}/rerun"
            waiting = member.post(rerun_url, headers={"Idempotency-Key": "before-archive"}).json()
            spare = self.upload(colleague, scene, self.photo("white"), "spare").json()

            archived = admin.post(scene + "/archive")
            self.assertEqual((archived.status_code, archived.json()["status"], archived.json()["archived_by"]),
                             (200, "archived", self.owner))
            self.assertEqual(member.post(scene + "/archive").json(), archived.json())
            self.assertEqual(colleague.get(scene).json(), archived.json())
            self.assertEqual(colleague.get("/api/scenes?status=active").json(), [])
            self.assertEqual(colleague.get("/api/scenes?status=archived").json(), [archived.json()])
            self.assertEqual(colleague.get("/api/scenes").json(), [archived.json()])
            self.assertEqual(colleague.post(scene + "/restore").status_code, 403)
            self.assertEqual(len(colleague.get(scene + "/frames").json()), 4)
            self.assertEqual(colleague.get(spare["image_url"]).status_code, 200)
            self.assertEqual(colleague.get(scene + "/revisions").json(), [revision])
            self.assertEqual(colleague.get(old["artifacts"][0]["url"]).status_code, 200)
            result_url = f"{scene}/revisions/{revision['revision_id']}/results"
            self.assertEqual(colleague.get(result_url).json()["splat"], old)

            for result in (
                member.patch(scene, json={"title": "只读"}),
                self.upload(member, scene, self.photo("green"), "archived-photo"),
                colleague.delete(scene + "/frames/" + spare["frame_id"]),
                member.post(scene + "/revisions", json={"frame_ids": [spare["frame_id"]]}),
                member.post("/api/jobs", json=payload),
                member.post(rerun_url, headers={"Idempotency-Key": "on-archive"}),
            ):
                self.assertEqual((result.status_code, result.json()["code"]), (409, "SCENE_ARCHIVED"))

            existing = self.claim(admin)
            self.assertEqual(existing["job_id"], waiting["job_id"])
            self.splat_output(existing)
            completed = self.complete_job(admin, existing)
            self.assertEqual(colleague.get(result_url).json()["splat"], completed)
            self.assertEqual(colleague.get(completed["artifacts"][0]["url"]).status_code, 200)

            outsider = TestClient(app, base_url=ORIGIN)
            self.addCleanup(outsider.close)
            self.logged_in(outsider, "outsider@example.test")
            self.assertEqual(outsider.post(scene + "/restore").status_code, 404)
            self.assertEqual(outsider.get(scene).status_code, 404)
            restored = member.post(scene + "/restore")
            self.assertEqual(restored.status_code, 200)
            self.assertEqual(restored.json()["status"], "active")
            self.assertIsNone(restored.json()["archived_at"])
            self.assertEqual(admin.post(scene + "/restore").json(), restored.json())
            self.assertEqual(self.upload(colleague, scene, self.photo("green"), "after").status_code, 201)
            self.assertEqual(colleague.get(result_url).json()["splat"], completed)

    def test_upload_rechecks_archive_after_decoding(self):
        app = create_app(self.settings)
        with TestClient(app, base_url=ORIGIN) as owner:
            member = TestClient(app, base_url=ORIGIN)
            self.addCleanup(member.close)
            self.logged_in(owner, "owner@example.test")
            self.logged_in(member, "member@example.test")
            scene = self.create_scene(owner)
            decoding, resume = Event(), Event()

            def pause_after_read(upload):
                data = read_image(upload)
                decoding.set()
                if not resume.wait(timeout=8):
                    raise RuntimeError("Timed out waiting for archive")
                return data

            with patch("src.api.platform.frames.read_image", side_effect=pause_after_read):
                with ThreadPoolExecutor(max_workers=1) as pool:
                    pending = pool.submit(self.upload, member, scene, self.photo())
                    try:
                        self.assertTrue(decoding.wait(timeout=8))
                        self.assertEqual(owner.post(scene + "/archive").json()["status"], "archived")
                    finally:
                        resume.set()
                    result = pending.result(timeout=10)
            self.assertEqual((result.status_code, result.json()["code"]), (409, "SCENE_ARCHIVED"))
            self.assertEqual(member.get(scene + "/frames").json(), [])
            self.assertEqual(list(app.state.photos.iterdir()), [])
