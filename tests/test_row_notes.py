"""Notatki rzędu: edycja i usuwanie (autor lub kierownik), ślad w dzienniku, powiadomienia na żywo."""
import json
import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("DATABASE_URL", f"sqlite:///{Path(tempfile.gettempdir()) / 'asolar-notes-test.db'}")
os.environ.setdefault("ASOLAR_SECRET", "test-only-secret")

from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.main import app
from app.models import AuditEvent, ConstructionRow

VARIANTS = ("1x28", "1x42", "1x56", "1x70", "1x42+1x28", "1x56+1x28", "1x56+1x42")


class RowNotesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)
        cls.manager = cls.login("kierownik", "Asolar2026!")
        cls.foreman1 = cls.login("brygadzista1", "Brygada1-2026!")
        cls.foreman2 = cls.login("brygadzista2", "Brygada2-2026!")
        cls.project_id = cls.client.post("/api/projects", headers=cls.manager, json={"name": "Notatki", "location": "Pole", "capacity_mw": 1}).json()["id"]
        zone = cls.client.post("/api/tracker-zones", headers=cls.manager, json={"project_id": cls.project_id, "name": "Strefa N"}).json()
        cls.client.put(f"/api/tracker-zones/{zone['id']}/config", headers=cls.manager, json={"items": [{"variant_code": v, "row_count": 2 if v == "1x28" else 0} for v in VARIANTS]})
        cls.rows = cls.client.get(f"/api/projects/{cls.project_id}/operational-rows", headers=cls.manager).json()

    @classmethod
    def tearDownClass(cls):
        cls.client.patch(f"/api/projects/{cls.project_id}", headers=cls.manager, json={"archived": True})
        cls.client.delete(f"/api/projects/{cls.project_id}", headers=cls.manager)

    @classmethod
    def login(cls, username, password):
        return {"Authorization": "Bearer " + cls.client.post("/api/auth/login", json={"username": username, "password": password}).json()["token"]}

    def note(self, row_id, headers, text, client_id):
        response = self.client.post(f"/api/rows/{row_id}/notes", headers=headers, json={"text": text, "client_id": client_id})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["id"]

    def notes(self, row_id):
        return self.client.get(f"/api/rows/{row_id}/notes", headers=self.manager).json()

    def current_note(self, row_id):
        with SessionLocal() as db:
            return db.get(ConstructionRow, row_id).note

    def test_author_edits_and_deletes_own_note_others_cannot(self):
        row_id = self.rows[0]["id"]
        first = self.note(row_id, self.foreman1, "Brak śruby M16", "n-edit-1")
        second = self.note(row_id, self.foreman1, "Literówka w notatcę", "n-edit-2")
        self.assertEqual(self.notes(row_id)[0]["author_id"], self.client.get("/api/auth/me", headers=self.foreman1).json()["id"])

        edited = self.client.patch(f"/api/rows/{row_id}/notes/{second}", headers=self.foreman1, json={"text": "  Literówka w notatce  "})
        self.assertEqual(edited.status_code, 200, edited.text)
        listed = next(item for item in self.notes(row_id) if item["id"] == second)
        self.assertEqual(listed["text"], "Literówka w notatce")
        self.assertEqual(listed["edited_by"], "Brygadzista 1")
        self.assertIsNotNone(listed["edited_at"])
        self.assertEqual(self.current_note(row_id), "Literówka w notatce")

        self.assertEqual(self.client.patch(f"/api/rows/{row_id}/notes/{first}", headers=self.foreman2, json={"text": "Nie moja"}).status_code, 403)
        self.assertEqual(self.client.delete(f"/api/rows/{row_id}/notes/{first}", headers=self.foreman2).status_code, 403)
        self.assertEqual(self.client.patch(f"/api/rows/{row_id}/notes/{first}", headers=self.foreman1, json={"text": ""}).status_code, 422)
        self.assertEqual(self.client.patch(f"/api/rows/{self.rows[1]['id']}/notes/{first}", headers=self.foreman1, json={"text": "Zły rząd"}).status_code, 404)

        # Usunięcie najnowszej notatki: „bieżąca notatka” rzędu wraca do poprzedniej.
        self.assertEqual(self.client.delete(f"/api/rows/{row_id}/notes/{second}", headers=self.foreman1).status_code, 200)
        self.assertEqual([item["id"] for item in self.notes(row_id)], [first])
        self.assertEqual(self.current_note(row_id), "Brak śruby M16")
        operational = next(row for row in self.client.get(f"/api/projects/{self.project_id}/operational-rows", headers=self.manager).json() if row["id"] == row_id)
        self.assertEqual(operational["notes_count"], 1)

        # Ponowne usunięcie (np. z kolejki offline drugiego telefonu) — 404, notatki już nie ma.
        self.assertEqual(self.client.delete(f"/api/rows/{row_id}/notes/{second}", headers=self.foreman1).status_code, 404)

    def test_manager_edits_and_deletes_any_note_and_text_stays_in_audit_log(self):
        row_id = self.rows[1]["id"]
        with SessionLocal() as db:
            start = db.query(AuditEvent.id).order_by(AuditEvent.id.desc()).limit(1).scalar() or 0
        note_id = self.note(row_id, self.foreman2, "Notatka do usunięcia przez kierownika", "n-mgr-1")
        self.assertEqual(self.client.patch(f"/api/rows/{row_id}/notes/{note_id}", headers=self.manager, json={"text": "Poprawione przez kierownika"}).status_code, 200)
        self.assertEqual(self.notes(row_id)[0]["edited_by"], "Kierownik Budowy")
        self.assertEqual(self.client.delete(f"/api/rows/{row_id}/notes/{note_id}", headers=self.manager).status_code, 200)
        self.assertEqual(self.notes(row_id), [])
        self.assertEqual(self.current_note(row_id), "")
        with SessionLocal() as db:
            events = db.query(AuditEvent).filter(AuditEvent.id > start, AuditEvent.entity_type == "row_note", AuditEvent.entity_id == note_id).order_by(AuditEvent.id).all()
        self.assertEqual([event.action for event in events], ["create", "update", "delete"])
        self.assertEqual(json.loads(events[1].details)["przed"], "Notatka do usunięcia przez kierownika")
        self.assertEqual(json.loads(events[2].details)["tresc"], "Poprawione przez kierownika")

    def test_note_change_is_broadcast_to_other_devices(self):
        row_id = self.rows[0]["id"]
        note_id = self.note(row_id, self.foreman1, "Do synchronizacji", "n-ws-1")
        token = self.manager["Authorization"].split(" ", 1)[1]
        with self.client.websocket_connect(f"/ws?token={token}") as ws:
            self.client.delete(f"/api/rows/{row_id}/notes/{note_id}", headers=self.foreman1)
            event = ws.receive_json()
            self.assertEqual((event["event"], event["payload"]["id"]), ("row.note", row_id))


if __name__ == "__main__":
    unittest.main()
