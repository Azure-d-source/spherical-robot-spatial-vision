import os
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Barrier
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

from src.api.images import MAX_BYTES, MAX_REQUEST
from src.api.platform.accounts import Account, COOKIE, LoginSession, Team, password_hasher, session_hash
from src.api.platform.app import create_app
from src.api.platform.config import PlatformSettings

DB_URL = os.environ.get("SPATIAL_TEST_DATABASE_URL")
MIGRATIONS = Path(__file__).resolve().parents[1] / "src/api/platform/alembic.ini"
ORIGIN = "https://workbench.example.test"


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
        self.settings = PlatformSettings(dsn.render_as_string(hide_password=False), ORIGIN, photos_dir)
        self.enterContext(patch.dict(os.environ, SPATIAL_DATABASE_URL=self.settings.database_url))
        command.upgrade(Config(str(MIGRATIONS)), "head")
        self.engine = create_engine(dsn)
        self.addCleanup(self.engine.dispose)

        self.owner = uuid4().hex
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
                Account(account_id=uuid4().hex, email="member@example.test", team_id=self.team,
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
