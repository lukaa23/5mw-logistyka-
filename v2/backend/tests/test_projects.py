"""ASOLAR v2, etap 1: izolacja danych budów, uprawnienia, cykl życia budowy, konta."""
import os
import unittest
import uuid

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from asolar2 import tenancy
from asolar2.config import IS_POSTGRES
from asolar2.main import app, bootstrap
from asolar2.registry import RegistrySession, User
from asolar2.security import create_token
from asolar2.tenancy import ProjectEvent, Zone

ADMIN_PASSWORD = os.environ["ASOLAR_ADMIN_PASSWORD"]


def unique(prefix):
    return f"{prefix} {uuid.uuid4().hex[:6]}"


class V2Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)
        cls.admin = cls.login("kierownik", ADMIN_PASSWORD)

    @classmethod
    def login(cls, username, password):
        response = cls.client.post("/api/auth/login", json={"username": username, "password": password})
        assert response.status_code == 200, response.text
        return {"Authorization": f"Bearer {response.json()['token']}"}

    def make_user(self, prefix="osoba", is_admin=False):
        username = f"{prefix}-{uuid.uuid4().hex[:6]}"
        created = self.client.post("/api/users", headers=self.admin, json={"username": username, "full_name": f"Test {username}", "password": "Haslo-testowe-1", "is_admin": is_admin})
        self.assertEqual(created.status_code, 200, created.text)
        return created.json(), self.login(username, "Haslo-testowe-1")

    def make_project(self, name=None):
        response = self.client.post("/api/projects", headers=self.admin, json={"name": name or unique("Farma"), "location": "Test", "capacity_mw": 5})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def add_member(self, project_id, user_id, role, headers=None):
        response = self.client.put(f"/api/projects/{project_id}/members", headers=headers or self.admin, json={"user_id": user_id, "role": role})
        self.assertEqual(response.status_code, 200, response.text)


class IsolationTest(V2Base):
    def test_each_project_gets_its_own_storage_and_data_does_not_mix(self):
        a, b = self.make_project(), self.make_project()
        key_a, key_b = tenancy.storage_key_for(a["id"]), tenancy.storage_key_for(b["id"])
        self.assertNotEqual(key_a, key_b)
        self.assertTrue(tenancy.storage_exists(key_a) and tenancy.storage_exists(key_b))
        self.assertTrue({"zones", "events"} <= tenancy.storage_tables(key_a))
        self.assertTrue({"zones", "events"} <= tenancy.storage_tables(key_b))

        created = self.client.post(f"/api/projects/{a['id']}/zones", headers=self.admin, json={"name": "Strefa A — północ"})
        self.assertEqual(created.status_code, 200, created.text)
        self.assertEqual([zone["name"] for zone in self.client.get(f"/api/projects/{a['id']}/zones", headers=self.admin).json()], ["Strefa A — północ"])
        self.assertEqual(self.client.get(f"/api/projects/{b['id']}/zones", headers=self.admin).json(), [])
        # Ta sama nazwa w innej budowie jest dozwolona — to osobna przestrzeń.
        self.assertEqual(self.client.post(f"/api/projects/{b['id']}/zones", headers=self.admin, json={"name": "Strefa A — północ"}).status_code, 200)
        self.assertEqual(self.client.post(f"/api/projects/{a['id']}/zones", headers=self.admin, json={"name": "strefa a — północ"}).status_code, 409)

        # Bezpośrednio w przestrzeniach: dane fizycznie rozdzielone.
        with tenancy.project_session(key_a) as session:
            self.assertEqual(session.scalar(select(func.count(Zone.id))), 1)
        with tenancy.project_session(key_b) as session:
            self.assertEqual(session.scalar(select(func.count(Zone.id))), 1)
            self.assertEqual(session.scalar(select(func.count(ProjectEvent.id)).where(ProjectEvent.entity == "zone")), 1)

        # Id strefy z budowy A nie istnieje w przestrzeni budowy B (inna tabela, nie filtr).
        zone_a = created.json()["id"]
        other = self.client.get(f"/api/projects/{b['id']}/zones", headers=self.admin).json()[0]["id"]
        if zone_a != other:
            self.assertEqual(self.client.delete(f"/api/projects/{b['id']}/zones/{zone_a}", headers=self.admin).status_code, 404)
        self.assertEqual(len(self.client.get(f"/api/projects/{a['id']}/zones", headers=self.admin).json()), 1)

    def test_storage_key_cannot_be_abused_for_sql(self):
        for bad in ("public", "proj_1; DROP TABLE users", "proj_x", "../registry"):
            with self.assertRaises(ValueError):
                tenancy.project_bind(bad)

    def test_isolation_mode_is_reported(self):
        health = self.client.get("/api/health").json()
        self.assertEqual(health["isolation"], "schema-per-project" if IS_POSTGRES else "file-per-project")


class AccessTest(V2Base):
    def test_foreman_sees_only_own_projects_and_cannot_manage(self):
        p1, p2 = self.make_project(), self.make_project()
        foreman, foreman_headers = self.make_user("brygadzista")
        self.add_member(p1["id"], foreman["id"], "brygadzista")

        visible = self.client.get("/api/projects", headers=foreman_headers).json()
        self.assertEqual([item["id"] for item in visible], [p1["id"]])
        self.assertEqual(visible[0]["role"], "brygadzista")
        # Budowa bez dostępu: „nie znaleziono” (nie zdradzamy jej istnienia).
        self.assertEqual(self.client.get(f"/api/projects/{p2['id']}", headers=foreman_headers).status_code, 404)
        self.assertEqual(self.client.get(f"/api/projects/{p2['id']}/zones", headers=foreman_headers).status_code, 404)
        self.assertEqual(self.client.post(f"/api/projects/{p2['id']}/zones", headers=foreman_headers, json={"name": "Włamanie"}).status_code, 404)

        zone = self.client.post(f"/api/projects/{p1['id']}/zones", headers=foreman_headers, json={"name": "Strefa brygady"})
        self.assertEqual(zone.status_code, 200)
        self.assertEqual(self.client.delete(f"/api/projects/{p1['id']}/zones/{zone.json()['id']}", headers=foreman_headers).status_code, 403)
        self.assertEqual(self.client.patch(f"/api/projects/{p1['id']}", headers=foreman_headers, json={"name": "Zmiana"}).status_code, 403)
        self.assertEqual(self.client.put(f"/api/projects/{p1['id']}/members", headers=foreman_headers, json={"user_id": foreman["id"], "role": "kierownik"}).status_code, 403)
        self.assertEqual(self.client.post("/api/projects", headers=foreman_headers, json={"name": "Moja budowa"}).status_code, 403)
        self.assertEqual(self.client.get("/api/users", headers=foreman_headers).status_code, 403)

    def test_project_manager_manages_own_project_only(self):
        p1, p2 = self.make_project(), self.make_project()
        manager, manager_headers = self.make_user("kierownik")
        foreman, foreman_headers = self.make_user("brygadzista")
        self.add_member(p1["id"], manager["id"], "kierownik")

        directory = self.client.get("/api/users", headers=manager_headers)
        self.assertEqual(directory.status_code, 200)
        self.add_member(p1["id"], foreman["id"], "brygadzista", headers=manager_headers)
        members = self.client.get(f"/api/projects/{p1['id']}/members", headers=manager_headers).json()
        self.assertEqual({item["user"]["id"]: item["role"] for item in members if item["user"]["id"] in (manager["id"], foreman["id"])}, {manager["id"]: "kierownik", foreman["id"]: "brygadzista"})
        self.assertEqual(self.client.put(f"/api/projects/{p2['id']}/members", headers=manager_headers, json={"user_id": foreman["id"], "role": "brygadzista"}).status_code, 404)
        self.assertEqual(self.client.put(f"/api/projects/{p1['id']}/members", headers=manager_headers, json={"user_id": manager["id"], "role": "brygadzista"}).status_code, 400)
        self.assertEqual(self.client.delete(f"/api/projects/{p1['id']}/members/{manager['id']}", headers=manager_headers).status_code, 400)
        self.assertEqual(self.client.delete(f"/api/projects/{p1['id']}/members/{foreman['id']}", headers=manager_headers).status_code, 200)
        self.assertEqual(self.client.get(f"/api/projects/{p1['id']}", headers=foreman_headers).status_code, 404)
        self.assertEqual(self.client.patch(f"/api/projects/{p1['id']}", headers=manager_headers, json={"location": "Nowa lokalizacja"}).json()["location"], "Nowa lokalizacja")
        self.assertEqual(self.client.post("/api/users", headers=manager_headers, json={"username": "x-test", "full_name": "X Y", "password": "Haslo-12345"}).status_code, 403)

    def test_admin_sees_all_projects(self):
        p = self.make_project()
        listed = {item["id"]: item for item in self.client.get("/api/projects", headers=self.admin).json()}
        self.assertEqual(listed[p["id"]]["role"], "kierownik")
        self.assertIn("zones", listed[p["id"]]["stats"])


class LifecycleTest(V2Base):
    def test_archive_and_controlled_delete_removes_only_that_storage(self):
        keep, remove = self.make_project(), self.make_project()
        self.client.post(f"/api/projects/{keep['id']}/zones", headers=self.admin, json={"name": "Zostaje"})
        self.client.post(f"/api/projects/{remove['id']}/zones", headers=self.admin, json={"name": "Do usunięcia"})
        key = tenancy.storage_key_for(remove["id"])

        self.assertEqual(self.client.delete(f"/api/projects/{remove['id']}?confirm_name={remove['name']}", headers=self.admin).status_code, 409)
        self.client.patch(f"/api/projects/{remove['id']}", headers=self.admin, json={"archived": True})
        self.assertEqual(self.client.post(f"/api/projects/{remove['id']}/zones", headers=self.admin, json={"name": "Po archiwizacji"}).status_code, 409)
        self.assertNotIn(remove["id"], [item["id"] for item in self.client.get("/api/projects", headers=self.admin).json()])
        self.assertIn(remove["id"], [item["id"] for item in self.client.get("/api/projects?include_archived=true", headers=self.admin).json()])
        self.assertEqual(self.client.delete(f"/api/projects/{remove['id']}?confirm_name=zla-nazwa", headers=self.admin).status_code, 400)
        self.assertEqual(self.client.delete(f"/api/projects/{remove['id']}?confirm_name={remove['name']}", headers=self.admin).status_code, 200)

        self.assertFalse(tenancy.storage_exists(key))
        self.assertEqual(self.client.get(f"/api/projects/{remove['id']}", headers=self.admin).status_code, 404)
        self.assertEqual([zone["name"] for zone in self.client.get(f"/api/projects/{keep['id']}/zones", headers=self.admin).json()], ["Zostaje"])

    def test_duplicate_active_name_rejected(self):
        project = self.make_project()
        self.assertEqual(self.client.post("/api/projects", headers=self.admin, json={"name": project["name"].upper()}).status_code, 409)

    def test_restart_keeps_data_and_passwords(self):
        project = self.make_project()
        self.client.post(f"/api/projects/{project['id']}/zones", headers=self.admin, json={"name": "Przed restartem"})
        with RegistrySession() as db:
            before = db.scalar(select(User).where(User.username == "kierownik")).password_hash
        bootstrap()  # symulacja ponownego uruchomienia serwera
        with RegistrySession() as db:
            self.assertEqual(db.scalar(select(User).where(User.username == "kierownik")).password_hash, before)
        self.assertEqual([zone["name"] for zone in self.client.get(f"/api/projects/{project['id']}/zones", headers=self.admin).json()], ["Przed restartem"])

    def test_project_event_log(self):
        project = self.make_project()
        zone = self.client.post(f"/api/projects/{project['id']}/zones", headers=self.admin, json={"name": "Z1"}).json()
        self.client.patch(f"/api/projects/{project['id']}/zones/{zone['id']}", headers=self.admin, json={"name": "Z1 — poprawiona"})
        events = self.client.get(f"/api/projects/{project['id']}/events", headers=self.admin).json()
        self.assertEqual([(event["action"], event["entity"]) for event in events][:3], [("update", "zone"), ("create", "zone"), ("create", "project")])
        self.assertEqual(events[0]["user"], "Kierownik Budowy")


class AuthTest(V2Base):
    def test_login_rules_and_tokens(self):
        self.assertEqual(self.client.post("/api/auth/login", json={"username": "kierownik", "password": "zle"}).status_code, 401)
        self.assertEqual(self.client.get("/api/projects").status_code, 401)
        self.assertEqual(self.client.get("/api/projects", headers={"Authorization": "Bearer falszywy.token"}).status_code, 401)
        user, headers = self.make_user("nieaktywny")
        self.client.patch(f"/api/users/{user['id']}", headers=self.admin, json={"active": False})
        self.assertEqual(self.client.get("/api/auth/me", headers=headers).status_code, 401)
        self.assertEqual(self.client.post("/api/auth/login", json={"username": user["username"], "password": "Haslo-testowe-1"}).status_code, 403)
        admin_id = self.client.get("/api/auth/me", headers=self.admin).json()["id"]
        self.assertEqual(self.client.patch(f"/api/users/{admin_id}", headers=self.admin, json={"is_admin": False}).status_code, 400)
        self.assertTrue(create_token(admin_id).count(".") == 1)
        with RegistrySession() as db:
            stored = db.get(User, user["id"]).password_hash
        self.assertTrue(stored.startswith("pbkdf2_sha256$") and "Haslo-testowe-1" not in stored)


if __name__ == "__main__":
    unittest.main()
