import copy
import json
import os
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from src.app import activities, app, hash_password


class AuthenticationAndPrivacyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.secret = "test-secret-with-more-than-thirty-two-bytes"
        cls.password = "test-password"
        cls.users = {
            "student@mergington.edu": {
                "password_hash": hash_password(cls.password),
                "role": "student",
            },
            "new-student@mergington.edu": {
                "password_hash": hash_password(cls.password),
                "role": "student",
            },
            "teacher@mergington.edu": {
                "password_hash": hash_password(cls.password),
                "role": "teacher",
                "activities": ["Chess Club"],
            },
            "other-teacher@mergington.edu": {
                "password_hash": hash_password(cls.password),
                "role": "teacher",
                "activities": ["Art Club"],
            },
            "admin@mergington.edu": {
                "password_hash": hash_password(cls.password),
                "role": "administrator",
            },
        }
        cls.environment = patch.dict(
            os.environ,
            {
                "AUTH_TOKEN_SECRET": cls.secret,
                "AUTH_USERS": json.dumps(cls.users),
            },
        )
        cls.environment.start()
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        cls.environment.stop()

    def setUp(self):
        self.activities_before = copy.deepcopy(activities)

    def tearDown(self):
        activities.clear()
        activities.update(self.activities_before)

    def login(self, username):
        response = self.client.post(
            "/auth/login",
            json={"username": username, "password": self.password},
        )
        self.assertEqual(response.status_code, 200)
        return response.json()["access_token"]

    def headers(self, token):
        return {"Authorization": f"Bearer {token}"}

    def test_login_rejects_bad_credentials(self):
        response = self.client.post(
            "/auth/login",
            json={"username": "student@mergington.edu", "password": "wrong"},
        )
        self.assertEqual(response.status_code, 401)

    def test_public_activity_listing_does_not_expose_student_emails(self):
        response = self.client.get("/activities")
        self.assertEqual(response.status_code, 200)
        chess = response.json()["Chess Club"]
        self.assertEqual(chess["participant_count"], 2)
        self.assertNotIn("participants", chess)
        self.assertNotIn("michael@mergington.edu", response.text)

    def test_unauthenticated_enrollment_is_rejected(self):
        response = self.client.post("/activities/Chess%20Club/signup")
        self.assertEqual(response.status_code, 401)

    def test_student_can_manage_only_their_own_enrollment(self):
        token = self.login("student@mergington.edu")

        response = self.client.post(
            "/activities/Chess%20Club/signup?email=someone-else@mergington.edu",
            headers=self.headers(token),
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(
            "student@mergington.edu", activities["Chess Club"]["participants"]
        )
        self.assertNotIn(
            "someone-else@mergington.edu", activities["Chess Club"]["participants"]
        )

        spoofed = self.client.post(
            "/activities/Chess%20Club/signup",
            json={"student_email": "someone-else@mergington.edu"},
            headers=self.headers(token),
        )
        self.assertEqual(spoofed.status_code, 403)

        enrollments = self.client.get("/me/enrollments", headers=self.headers(token))
        self.assertEqual(enrollments.status_code, 200)
        self.assertEqual(
            [item["name"] for item in enrollments.json()["activities"]],
            ["Chess Club"],
        )

        response = self.client.delete(
            "/activities/Chess%20Club/unregister?email=michael@mergington.edu",
            headers=self.headers(token),
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(
            "michael@mergington.edu", activities["Chess Club"]["participants"]
        )
        self.assertNotIn(
            "student@mergington.edu", activities["Chess Club"]["participants"]
        )

        response = self.client.get(
            "/activities/Chess%20Club/participants",
            headers=self.headers(token),
        )
        self.assertEqual(response.status_code, 403)

    def test_teacher_roster_access_is_limited_to_assigned_activities(self):
        token = self.login("teacher@mergington.edu")
        allowed = self.client.get(
            "/activities/Chess%20Club/participants",
            headers=self.headers(token),
        )
        self.assertEqual(allowed.status_code, 200)
        self.assertIn("michael@mergington.edu", allowed.json()["participants"])

        denied = self.client.get(
            "/activities/Art%20Club/participants",
            headers=self.headers(token),
        )
        self.assertEqual(denied.status_code, 403)

        denied_signup = self.client.post(
            "/activities/Chess%20Club/signup",
            headers=self.headers(token),
        )
        self.assertEqual(denied_signup.status_code, 422)

        unknown_student = self.client.post(
            "/activities/Chess%20Club/signup",
            json={"student_email": "unknown@mergington.edu"},
            headers=self.headers(token),
        )
        self.assertEqual(unknown_student.status_code, 422)

        enrolled = self.client.post(
            "/activities/Chess%20Club/signup",
            json={"student_email": "new-student@mergington.edu"},
            headers=self.headers(token),
        )
        self.assertEqual(enrolled.status_code, 200)
        self.assertIn(
            "new-student@mergington.edu", activities["Chess Club"]["participants"]
        )

        out_of_scope = self.client.post(
            "/activities/Art%20Club/signup",
            json={"student_email": "new-student@mergington.edu"},
            headers=self.headers(token),
        )
        self.assertEqual(out_of_scope.status_code, 403)

        removed = self.client.request(
            "DELETE",
            "/activities/Chess%20Club/unregister",
            json={"student_email": "new-student@mergington.edu"},
            headers=self.headers(token),
        )
        self.assertEqual(removed.status_code, 200)
        self.assertNotIn(
            "new-student@mergington.edu", activities["Chess Club"]["participants"]
        )

    def test_administrator_can_view_rosters_for_any_activity(self):
        token = self.login("admin@mergington.edu")
        response = self.client.get(
            "/activities/Art%20Club/participants",
            headers=self.headers(token),
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("amelia@mergington.edu", response.json()["participants"])

        enrolled = self.client.post(
            "/activities/Art%20Club/signup",
            json={"student_email": "new-student@mergington.edu"},
            headers=self.headers(token),
        )
        self.assertEqual(enrolled.status_code, 200)
        self.assertIn(
            "new-student@mergington.edu", activities["Art Club"]["participants"]
        )

    def test_invalid_token_is_rejected(self):
        response = self.client.get(
            "/me/enrollments",
            headers={"Authorization": "Bearer invalid.token.value"},
        )
        self.assertEqual(response.status_code, 401)


if __name__ == "__main__":
    unittest.main()
