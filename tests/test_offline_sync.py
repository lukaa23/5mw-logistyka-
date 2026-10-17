"""Synchronizacja offline: ponowne wysyłanie z kolejki telefonu, czas zmiany, kopia zapasowa."""
import os
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

os.environ.setdefault("DATABASE_URL", f"sqlite:///{Path(tempfile.gettempdir()) / 'asolar-offline-test.db'}")
os.environ.setdefault("ASOLAR_SECRET", "test-only-secret")

from fastapi.testclient import TestClient

from app.main import app

VARIANTS = ("1x28", "1x42", "1x56", "1x70", "1x42+1x28", "1x56+1x28", "1x56+1x42")
PNG = b"\x89PNG\r\n\x1a\n" + b"1" * 32


class OfflineSyncTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)
        cls.manager = cls.login("kierownik", "Asolar2026!")
        cls.foreman = cls.login("brygadzista1", "Brygada1-2026!")
        project = cls.client.post("/api/projects", headers=cls.manager, json={"name": "Offline", "location": "Pole", "capacity_mw": 1}).json()
        cls.project_id = project["id"]
        zone = cls.client.post("/api/tracker-zones", headers=cls.manager, json={"project_id": cls.project_id, "name": "Strefa offline"}).json()
        cls.client.put(f"/api/tracker-zones/{zone['id']}/config", headers=cls.manager, json={"items": [{"variant_code": v, "row_count": 2 if v == "1x28" else 0} for v in VARIANTS]})
        cls.rows = cls.client.get(f"/api/projects/{cls.project_id}/operational-rows", headers=cls.manager).json()

    @classmethod
    def tearDownClass(cls):
        cls.client.patch(f"/api/projects/{cls.project_id}", headers=cls.manager, json={"archived": True})
        cls.client.delete(f"/api/projects/{cls.project_id}", headers=cls.manager)

    @classmethod
    def login(cls, username, password):
        return {"Authorization": "Bearer " + cls.client.post("/api/auth/login", json={"username": username, "password": password}).json()["token"]}

    def test_photo_resent_from_offline_queue_is_not_duplicated(self):
        row = self.rows[0]
        form = {"client_id": "phone-photo-1", "client_time": "2026-10-17T06:15:00Z"}
        first = self.client.post(f"/api/row/{row['id']}/photos", headers=self.foreman, data=form, files={"file": ("a.jpg", PNG, "image/jpeg")})
        second = self.client.post(f"/api/row/{row['id']}/photos", headers=self.foreman, data=form, files={"file": ("a.jpg", PNG, "image/jpeg")})
        self.assertEqual(first.status_code, 200, first.text)
        self.assertTrue(second.json()["deduplicated"])
        self.assertEqual(second.json()["id"], first.json()["id"])
        photos = self.client.get(f"/api/row/{row['id']}/photos", headers=self.manager).json()
        self.assertEqual(len([item for item in photos if item["id"] == first.json()["id"]]), 1)

    def test_offline_change_keeps_time_from_phone_but_rejects_future(self):
        row = self.rows[1]
        taken = (datetime.now(timezone.utc) - timedelta(hours=3)).replace(microsecond=0)
        result = self.client.patch(f"/api/rows/{row['id']}", headers=self.foreman, json={"built": True, "client_time": taken.isoformat()}).json()
        self.assertEqual(datetime.fromisoformat(result["built_at"]), taken.replace(tzinfo=None))
        self.client.patch(f"/api/rows/{row['id']}", headers=self.foreman, json={"built": False})
        future = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()
        result = self.client.patch(f"/api/rows/{row['id']}", headers=self.foreman, json={"built": True, "client_time": future}).json()
        self.assertLess(datetime.fromisoformat(result["built_at"]), datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(minutes=1))

        note = self.client.post(f"/api/rows/{row['id']}/notes", headers=self.foreman, json={"text": "Zapisane bez zasięgu", "client_id": "offline-note-time", "client_time": taken.isoformat()})
        self.assertEqual(note.status_code, 200)
        stored = next(item for item in self.client.get(f"/api/rows/{row['id']}/notes", headers=self.manager).json() if item["text"] == "Zapisane bez zasięgu")
        self.assertEqual(datetime.fromisoformat(stored["created_at"]), taken.replace(tzinfo=None))

    def test_photo_for_worklog_created_offline_is_attached_by_client_id(self):
        missing = self.client.post("/api/worklog/by-client/nie-ma/photos", headers=self.foreman, files={"file": ("m.png", PNG, "image/png")})
        self.assertEqual(missing.status_code, 404)
        log = {"project_id": self.project_id, "work_date": "2026-10-17", "team": "B1", "stage": "Płatwie", "people": 3, "hours": 8, "rows_completed": 1, "client_id": "offline-log-1"}
        log_id = self.client.post("/api/worklogs", headers=self.foreman, json=log).json()["id"]
        uploaded = self.client.post("/api/worklog/by-client/offline-log-1/photos", headers=self.foreman, data={"client_id": "offline-log-photo-1"}, files={"file": ("m.png", PNG, "image/png")})
        self.assertEqual(uploaded.status_code, 200, uploaded.text)
        self.assertEqual(len(self.client.get(f"/api/worklog/{log_id}/photos", headers=self.manager).json()), 1)
        self.assertEqual(self.client.post("/api/row/by-client/x/photos", headers=self.foreman, files={"file": ("m.png", PNG, "image/png")}).status_code, 400)

    def test_manager_backup_is_a_valid_sqlite_copy(self):
        self.assertEqual(self.client.get("/api/admin/backup", headers=self.foreman).status_code, 403)
        response = self.client.get("/api/admin/backup", headers=self.manager)
        if not os.environ["DATABASE_URL"].startswith("sqlite"):
            # PostgreSQL (Render): kopię wykonuje się pg_dump, endpoint to wyjaśnia.
            self.assertEqual(response.status_code, 400)
            self.assertIn("pg_dump", response.json()["detail"])
            return
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.content.startswith(b"SQLite format 3"))
        path = Path(tempfile.gettempdir()) / "asolar-backup-check.db"
        path.write_bytes(response.content)
        db = sqlite3.connect(path)
        try:
            self.assertGreaterEqual(db.execute("select count(*) from users").fetchone()[0], 3)
            self.assertGreaterEqual(db.execute("select count(*) from projects where name='Offline'").fetchone()[0], 1)
        finally:
            db.close()
        path.unlink()

    def test_server_info_is_manager_only(self):
        self.assertEqual(self.client.get("/api/server-info", headers=self.foreman).status_code, 403)
        info = self.client.get("/api/server-info", headers=self.manager).json()
        self.assertIn("HTTPS", info["note"])


if __name__ == "__main__":
    unittest.main()
