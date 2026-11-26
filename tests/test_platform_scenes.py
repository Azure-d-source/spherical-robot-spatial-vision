import os
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, update
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateSchema, DropSchema

from src.api.platform.accounts import Account, COOKIE, LoginSession, Team, password_hasher, session_hash
from src.api.platform.app import create_app
from src.api.platform.config import PlatformSettings

DB_URL = os.environ.get("SPATIAL_TEST_DATABASE_URL")
MIGRATIONS = Path(__file__).resolve().parents[1] / "src/api/platform/alembic.ini"
ORIGIN = "https://workbench.example.test"


@unittest.skipUnless(DB_URL, "SPATIAL_TEST_DATABASE_URL is required for PostgreSQL integration tests")
class PlatformSceneTests(unittest.TestCase):
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
        self.settings = PlatformSettings(dsn.render_as_string(hide_password=False), ORIGIN)
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
