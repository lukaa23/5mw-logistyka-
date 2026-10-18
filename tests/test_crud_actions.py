"""Komplet akcji edycji i usuwania: RFI, zdjęcia, dokumenty pomocnicze — z uprawnieniami w backendzie."""
import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("DATABASE_URL", f"sqlite:///{Path(tempfile.gettempdir()) / 'asolar-crud-test.db'}")
os.environ.setdefault("ASOLAR_SECRET", "test-only-secret")

from fastapi.testclient import TestClient

from app.main import app

PNG = b"\x89PNG\r\n\x1a\n" + b"2" * 32


class CrudActionsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)
        cls.manager = cls.login("kierownik", "Asolar2026!")
        cls.foreman1 = cls.login("brygadzista1", "Brygada1-2026!")
        cls.foreman2 = cls.login("brygadzista2", "Brygada2-2026!")
        cls.project_id = cls.client.post("/api/projects", headers=cls.manager, json={"name": "CRUD", "location": "Pole", "capacity_mw": 1}).json()["id"]

    @classmethod
    def tearDownClass(cls):
        cls.client.patch(f"/api/projects/{cls.project_id}", headers=cls.manager, json={"archived": True})
        cls.client.delete(f"/api/projects/{cls.project_id}", headers=cls.manager)

    @classmethod
    def login(cls, username, password):
        return {"Authorization": "Bearer " + cls.client.post("/api/auth/login", json={"username": username, "password": password}).json()["token"]}

    def rfi(self, headers, title="Kolizja"):
        response = self.client.post("/api/rfis", headers=headers, json={"project_id": self.project_id, "title": title, "description": "Opis", "priority": "normalny"})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["id"]

    def listed(self, rfi_id):
        return next((item for item in self.client.get(f"/api/rfis?project_id={self.project_id}", headers=self.manager).json() if item["id"] == rfi_id), None)

    def test_rfi_edit_permissions_and_delete(self):
        rfi_id = self.rfi(self.foreman1, "Literówka w tytule")
        self.assertEqual(self.listed(rfi_id)["created_by_id"], self.client.get("/api/auth/me", headers=self.foreman1).json()["id"])
        fixed = self.client.patch(f"/api/rfis/{rfi_id}", headers=self.foreman1, json={"title": "Kolizja słupa z drogą", "description": "Poprawiony opis", "priority": "wysoki"})
        self.assertEqual(fixed.status_code, 200, fixed.text)
        self.assertEqual((self.listed(rfi_id)["title"], self.listed(rfi_id)["priority"]), ("Kolizja słupa z drogą", "wysoki"))
        self.assertEqual(self.client.patch(f"/api/rfis/{rfi_id}", headers=self.foreman2, json={"title": "Nie moje"}).status_code, 403)
        self.assertEqual(self.client.patch(f"/api/rfis/{rfi_id}", headers=self.foreman1, json={"status": "zamknięty"}).status_code, 403)
        self.assertEqual(self.client.patch(f"/api/rfis/{rfi_id}", headers=self.foreman1, json={"title": ""}).status_code, 422)
        self.assertEqual(self.client.patch(f"/api/rfis/{rfi_id}", headers=self.manager, json={"status": "zamknięty"}).status_code, 200)
        self.assertEqual(self.client.patch(f"/api/rfis/{rfi_id}", headers=self.foreman1, json={"title": "Po zamknięciu"}).status_code, 409)

        self.client.post(f"/api/rfi/{rfi_id}/photos", headers=self.foreman1, files={"file": ("r.png", PNG, "image/png")})
        self.assertEqual(self.client.delete(f"/api/rfis/{rfi_id}", headers=self.foreman1).status_code, 403)
        self.assertEqual(self.client.delete(f"/api/rfis/{rfi_id}", headers=self.manager).status_code, 200)
        self.assertIsNone(self.listed(rfi_id))
        self.assertEqual(self.client.get(f"/api/rfi/{rfi_id}/photos", headers=self.manager).json(), [])
        self.assertEqual(self.client.delete(f"/api/rfis/{rfi_id}", headers=self.manager).status_code, 404)

    def test_photo_delete_by_author_or_manager_only(self):
        rfi_id = self.rfi(self.foreman1)
        own = self.client.post(f"/api/rfi/{rfi_id}/photos", headers=self.foreman1, files={"file": ("a.png", PNG, "image/png")}).json()["id"]
        other = self.client.post(f"/api/rfi/{rfi_id}/photos", headers=self.foreman1, files={"file": ("b.png", PNG, "image/png")}).json()["id"]
        photos = self.client.get(f"/api/rfi/{rfi_id}/photos", headers=self.manager).json()
        self.assertTrue(all("uploaded_by_id" in item for item in photos))
        self.assertEqual(self.client.delete(f"/api/attachments/{own}", headers=self.foreman2).status_code, 403)
        self.assertEqual(self.client.delete(f"/api/attachments/{own}", headers=self.foreman1).status_code, 200)
        self.assertEqual(self.client.delete(f"/api/attachments/{other}", headers=self.manager).status_code, 200)
        self.assertEqual(self.client.get(f"/api/rfi/{rfi_id}/photos", headers=self.manager).json(), [])
        self.assertEqual(self.client.get(f"/api/attachments/{own}", headers=self.manager).status_code, 404)

    def test_supplemental_document_delete_and_source_protection(self):
        uploaded = self.client.post("/api/documents", headers=self.foreman1, data={"project_id": str(self.project_id)}, files={"file": ("notatka.pdf", b"not a pdf", "application/pdf")}).json()
        self.assertEqual(self.client.delete(f"/api/documents/{uploaded['id']}", headers=self.foreman1).status_code, 403)
        self.assertEqual(self.client.delete(f"/api/documents/{uploaded['id']}", headers=self.manager).status_code, 200)
        self.assertEqual(self.client.get(f"/api/documents/{uploaded['id']}/file", headers=self.manager).status_code, 404)
        source_project = next(item for item in self.client.get("/api/projects", headers=self.manager).json() if item["name"] == "RF-GIULIETTA")
        approved = next(item for item in self.client.get(f"/api/documents?project_id={source_project['id']}", headers=self.manager).json() if item["approved_source"])
        self.assertEqual(self.client.delete(f"/api/documents/{approved['id']}", headers=self.manager).status_code, 409)

    def test_user_edit_name_and_role(self):
        created = self.client.post("/api/users", headers=self.manager, json={"username": "edycja-test", "full_name": "Jan Kowalsky", "role": "brygadzista", "password": "Haslo-12345"}).json()
        edited = self.client.patch(f"/api/users/{created['id']}", headers=self.manager, json={"full_name": "Jan Kowalski", "role": "kierownik"})
        self.assertEqual(edited.status_code, 200)
        self.assertEqual((edited.json()["full_name"], edited.json()["role"]), ("Jan Kowalski", "kierownik"))
        self.assertEqual(self.client.patch(f"/api/users/{created['id']}", headers=self.foreman1, json={"full_name": "X"}).status_code, 403)


if __name__ == "__main__":
    unittest.main()
