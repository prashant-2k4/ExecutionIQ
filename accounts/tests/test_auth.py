from datetime import date, timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from core.models import ExecutionLog, Goal, Task


class RegistrationLoginTests(TestCase):
    def test_register_creates_user_and_logs_in(self):
        response = self.client.post(reverse("register"), {
            "username": "bob",
            "email": "bob@example.com",
            "password1": "a-strong-pass-951",
            "password2": "a-strong-pass-951",
        })
        self.assertRedirects(response, reverse("goal_list"))
        self.assertTrue(User.objects.filter(username="bob").exists())
        self.assertEqual(int(self.client.session["_auth_user_id"]), User.objects.get().id)

    def test_register_rejects_mismatched_passwords(self):
        response = self.client.post(reverse("register"), {
            "username": "bob",
            "password1": "a-strong-pass-951",
            "password2": "different-pass-951",
        })
        self.assertEqual(response.status_code, 200)
        self.assertFalse(User.objects.exists())

    def test_login_and_logout(self):
        User.objects.create_user("bob", password="a-strong-pass-951")

        response = self.client.post(reverse("login"), {
            "username": "bob",
            "password": "a-strong-pass-951",
        })
        self.assertRedirects(response, reverse("goal_list"))

        response = self.client.post(reverse("logout"))
        self.assertRedirects(response, reverse("login"))
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_login_with_wrong_password_fails(self):
        User.objects.create_user("bob", password="a-strong-pass-951")
        response = self.client.post(reverse("login"), {"username": "bob", "password": "nope"})
        self.assertContains(response, "Invalid username or password")

    def test_pages_require_login(self):
        for name, args in [
            ("goal_list", []),
            ("create_goal", []),
            ("ai_plan", []),
            ("create_task", [1]),
            ("edit_task", [1]),
            ("log_work", [1]),
        ]:
            with self.subTest(page=name):
                url = reverse(name, args=args)
                response = self.client.get(url)
                self.assertRedirects(response, f"{reverse('login')}?next={url}")


class OwnershipTests(TestCase):
    """A user must never see or change another user's goals, tasks or logs."""

    def setUp(self):
        self.owner = User.objects.create_user("owner")
        self.intruder = User.objects.create_user("intruder")
        self.goal = Goal.objects.create(
            user=self.owner,
            title="Owner secret goal",
            deadline=date.today() + timedelta(days=10),
            daily_available_hours=2,
        )
        self.task = Task.objects.create(goal=self.goal, title="Owner task", estimated_hours=3)
        self.client.force_login(self.intruder)

    def test_goal_list_shows_only_own_goals(self):
        response = self.client.get(reverse("goal_list"))
        self.assertNotContains(response, "Owner secret goal")

    def test_other_users_records_return_404(self):
        requests = [
            ("get", reverse("create_task", args=[self.goal.id])),
            ("post", reverse("create_task", args=[self.goal.id])),
            ("get", reverse("edit_task", args=[self.task.id])),
            ("post", reverse("edit_task", args=[self.task.id])),
            ("post", reverse("toggle_task", args=[self.task.id])),
            ("get", reverse("log_work", args=[self.task.id])),
            ("post", reverse("log_work", args=[self.task.id])),
        ]
        for method, url in requests:
            with self.subTest(method=method, url=url):
                response = getattr(self.client, method)(url, {
                    "title": "hijack",
                    "estimated_hours": "1",
                    "status": "COMPLETED",
                    "priority": "LOW",
                    "date": date.today().isoformat(),
                    "duration_minutes": 60,
                })
                self.assertEqual(response.status_code, 404)

        self.task.refresh_from_db()
        self.assertEqual(self.task.title, "Owner task")
        self.assertEqual(self.task.status, Task.Status.TODO)
        self.assertEqual(self.goal.tasks.count(), 1)
        self.assertFalse(ExecutionLog.objects.exists())
