"""
@changelog
| Version | Description                                            | Reference                                     |
| v1.0.0 | Initial implementation (indexed baseline)              |                                               |
| v1.1.0 | Added unit tests for import_course_members_with_groups and CourseMembershipsImportView | REQ: 20260908-课程名单分组导入 TECH: 04_design_tech-design.md §3.4 |
| v1.1.1 | Regression test: pre-enrolled member without a group assigned to an existing group | REQ: 20260908-课程名单分组导入 TECH: E2E-001 defect |
/@changelog

@author chuckyang123
"""
from unittest.mock import patch

from django.urls import reverse
from rest_framework.test import APITestCase, APIClient

from users.models import User
from .logic import import_course_members_with_groups
from .models import (
    Course,
    CourseGroup,
    CourseGroupMember,
    CourseMembership,
    Role,
)


class ImportCourseMembersWithGroupsTestCase(APITestCase):
    def setUp(self) -> None:
        self.owner = User.objects.create(email="owner@example.com", name="Owner")
        self.course = Course.objects.create(
            owner=self.owner,
            name="Test Course",
            description="",
            is_published=True,
        )
        self.membership_owner = CourseMembership.objects.create(
            user=self.owner, course=self.course, role=Role.CO_OWNER
        )

    def create_user(self, email: str, name: str = "Student"):
        return User.objects.create(email=email, name=name)

    def create_membership(self, user: User, role=Role.STUDENT):
        return CourseMembership.objects.create(
            user=user, course=self.course, role=role
        )

    def create_group(self, name: str):
        return CourseGroup.objects.create(course=self.course, name=name)

    def test_import_new_users_without_group_succeeds(self) -> None:
        rows = [
            {"email": "alice@example.com", "name": "Alice", "group": ""},
            {"email": "bob@example.com", "name": "Bob"},
        ]
        result = import_course_members_with_groups(course=self.course, rows=rows)

        self.assertEqual(result["summary"]["total"], 2)
        self.assertEqual(result["summary"]["succeeded"], 2)
        self.assertEqual(result["summary"]["failed"], 0)
        self.assertEqual(result["summary"]["usersCreated"], 2)
        self.assertEqual(result["summary"]["membershipsCreated"], 2)
        self.assertEqual(result["summary"]["groupsCreated"], 0)
        self.assertEqual(
            CourseMembership.objects.filter(course=self.course).count(), 3
        )
        self.assertEqual(CourseGroup.objects.filter(course=self.course).count(), 0)
        self.assertTrue(
            all(row["status"] == "success" for row in result["rows"])
        )

    def test_existing_user_without_group_is_already_enrolled(self) -> None:
        existing = self.create_user("carol@example.com")
        self.create_membership(existing)

        result = import_course_members_with_groups(
            course=self.course,
            rows=[{"email": "carol@example.com", "name": "Carol"}],
        )

        self.assertEqual(result["summary"]["succeeded"], 1)
        self.assertEqual(result["summary"]["usersCreated"], 0)
        self.assertEqual(result["summary"]["membershipsCreated"], 0)
        self.assertEqual(result["rows"][0]["code"], "already_enrolled")
        self.assertEqual(
            CourseMembership.objects.filter(course=self.course).count(), 2
        )

    def test_pre_enrolled_member_without_group_joins_existing_group(self) -> None:
        student = self.create_user("noel@example.com")
        membership = self.create_membership(student)
        group = self.create_group("Team A")

        result = import_course_members_with_groups(
            course=self.course,
            rows=[{"email": "noel@example.com", "name": "Noel", "group": "Team A"}],
        )

        self.assertEqual(result["summary"]["succeeded"], 1)
        self.assertEqual(result["summary"]["failed"], 0)
        self.assertEqual(result["rows"][0]["code"], "added_to_group")
        self.assertTrue(
            CourseGroupMember.objects.filter(member=membership, group=group).exists()
        )

    def test_duplicate_email_in_file_skips_second_row(self) -> None:
        rows = [
            {"email": "dave@example.com", "name": "Dave"},
            {"email": "dave@example.com", "name": "Dave Clone"},
        ]
        result = import_course_members_with_groups(course=self.course, rows=rows)

        self.assertEqual(result["summary"]["succeeded"], 1)
        self.assertEqual(result["summary"]["failed"], 1)
        self.assertEqual(result["rows"][1]["status"], "error")
        self.assertEqual(result["rows"][1]["code"], "duplicate_email")
        self.assertEqual(result["summary"]["usersCreated"], 1)
        self.assertEqual(
            CourseMembership.objects.filter(course=self.course).count(), 2
        )

    def test_invalid_email_rows_are_skipped(self) -> None:
        rows = [
            {"email": "not-an-email", "name": "Bad"},
            {"email": "erin@example.com", "name": "Erin"},
        ]
        result = import_course_members_with_groups(course=self.course, rows=rows)

        self.assertEqual(result["summary"]["failed"], 1)
        self.assertEqual(result["summary"]["succeeded"], 1)
        self.assertEqual(result["rows"][0]["code"], "invalid_email")
        self.assertEqual(result["summary"]["usersCreated"], 1)

    def test_group_matches_existing_group_case_insensitively(self) -> None:
        self.create_group("Existing A")
        result = import_course_members_with_groups(
            course=self.course,
            rows=[{"email": "frank@example.com", "name": "Frank", "group": " existing a "}],
        )

        self.assertEqual(result["summary"]["succeeded"], 1)
        self.assertEqual(result["summary"]["groupsCreated"], 0)
        group = CourseGroup.objects.get(course=self.course, name="Existing A")
        membership = CourseMembership.objects.get(
            course=self.course, user__email="frank@example.com"
        )
        self.assertTrue(
            CourseGroupMember.objects.filter(
                member=membership, group=group
            ).exists()
        )

    def test_new_group_is_created_once_for_case_variants(self) -> None:
        rows = [
            {"email": "grace@example.com", "name": "Grace", "group": "Team 1"},
            {"email": "heidi@example.com", "name": "Heidi", "group": "team 1"},
        ]
        result = import_course_members_with_groups(course=self.course, rows=rows)

        self.assertEqual(result["summary"]["succeeded"], 2)
        self.assertEqual(result["summary"]["groupsCreated"], 1)
        groups = CourseGroup.objects.filter(course=self.course)
        self.assertEqual(groups.count(), 1)
        self.assertEqual(groups.first().name, "Team 1")

        first_membership = CourseMembership.objects.get(
            course=self.course, user__email="grace@example.com"
        )
        second_membership = CourseMembership.objects.get(
            course=self.course, user__email="heidi@example.com"
        )
        self.assertTrue(
            CourseGroupMember.objects.filter(
                member=first_membership, group=groups.first()
            ).exists()
        )
        self.assertTrue(
            CourseGroupMember.objects.filter(
                member=second_membership, group=groups.first()
            ).exists()
        )

    def test_member_already_in_target_group_is_success(self) -> None:
        student = self.create_user("ivan@example.com")
        membership = self.create_membership(student)
        group = self.create_group("Group A")
        CourseGroupMember.objects.create(member=membership, group=group)

        result = import_course_members_with_groups(
            course=self.course,
            rows=[{"email": "ivan@example.com", "name": "Ivan", "group": "GROUP A"}],
        )

        self.assertEqual(result["summary"]["failed"], 0)
        self.assertEqual(result["rows"][0]["code"], "already_in_group")
        self.assertEqual(
            CourseGroupMember.objects.filter(member=membership).count(), 1
        )

    def test_member_in_another_group_is_error(self) -> None:
        student = self.create_user("judy@example.com")
        membership = self.create_membership(student)
        group_a = self.create_group("Group A")
        CourseGroupMember.objects.create(member=membership, group=group_a)

        result = import_course_members_with_groups(
            course=self.course,
            rows=[{"email": "judy@example.com", "name": "Judy", "group": "Group B"}],
        )

        self.assertEqual(result["summary"]["failed"], 1)
        self.assertEqual(result["rows"][0]["code"], "in_another_group")
        self.assertFalse(
            CourseGroup.objects.filter(course=self.course, name="Group B").exists()
        )
        self.assertEqual(
            CourseGroupMember.objects.filter(member=membership).count(), 1
        )

    def test_whitespace_only_group_does_not_create_group(self) -> None:
        result = import_course_members_with_groups(
            course=self.course,
            rows=[{"email": "karl@example.com", "name": "Karl", "group": "   "}],
        )

        self.assertEqual(result["summary"]["succeeded"], 1)
        self.assertEqual(result["summary"]["groupsCreated"], 0)
        self.assertEqual(CourseGroup.objects.filter(course=self.course).count(), 0)

    def test_overlong_group_name_is_invalid(self) -> None:
        result = import_course_members_with_groups(
            course=self.course,
            rows=[
                {
                    "email": "liam@example.com",
                    "name": "Liam",
                    "group": "X" * 300,
                }
            ],
        )

        self.assertEqual(result["summary"]["failed"], 1)
        self.assertEqual(result["rows"][0]["code"], "invalid_group_name")
        self.assertEqual(CourseGroup.objects.filter(course=self.course).count(), 0)

    def test_import_requires_co_owner_role(self) -> None:
        student = self.create_user("student@example.com")
        self.create_membership(student)
        url = reverse("course_memberships_import", args=[self.course.id])

        with patch.object(User, "is_authenticated", True, create=True):
            client = APIClient()
            client.force_authenticate(user=student)
            response = client.post(
                url,
                data={"rows": [{"email": "new@example.com", "name": "New"}]},
                format="json",
            )

        self.assertEqual(response.status_code, 403)

    def test_import_view_succeeds_for_co_owner(self) -> None:
        url = reverse("course_memberships_import", args=[self.course.id])

        with patch.object(User, "is_authenticated", True, create=True):
            client = APIClient()
            client.force_authenticate(user=self.owner)
            response = client.post(
                url,
                data={
                    "rows": [
                        {"email": "mia@example.com", "name": "Mia", "group": "Team A"},
                        {"email": "noah@example.com", "name": "Noah"},
                    ]
                },
                format="json",
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["summary"]["succeeded"], 2)
        self.assertEqual(response.data["summary"]["groupsCreated"], 1)
