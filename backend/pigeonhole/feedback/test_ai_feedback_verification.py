"""
Temporary verification tests for the two AI feedback features:
1. AI Feedback Answer Version Tracking (commit 0a9347a)
2. Playtest AI Score Visibility Control (commit c95a5da)

Run from backend/:
    .\\.venv\\Scripts\\python.exe pigeonhole\\manage.py test feedback.test_ai_feedback_verification

NOTE: Temporary file for verification only. Safe to delete after verification.
"""
import os
import uuid
from datetime import timedelta
from unittest import mock

from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone as tz
from rest_framework.test import APIClient

from courses.models import (
    Course,
    CourseMembership,
    CourseMilestone,
    CourseMilestoneTemplate,
    CourseSettings,
    CourseSubmission,
    Role,
    SubmissionType,
)
from feedback.logic import ai_feedback_record_to_json, create_feedback_version_and_record
from feedback.models import AIFeedbackRecord, FeedbackAnswerVersion, FeedbackInitialResponse
from forms.models import Form
from rest_framework_simplejwt.tokens import RefreshToken
from users.models import AccountType, User

RECORDS_URL = "/api/feedback/records/"


def jwt_client(user):
    """APIClient authenticated via a real SimpleJWT token (like production)."""
    access = RefreshToken.for_user(user).access_token
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")
    return client


class AIFeedbackBase(TestCase):
    def setUp(self):
        self.educator = User.objects.create(
            name="Teacher", email="teacher@test.com",
            account_type=AccountType.EDUCATOR, is_activated=True,
        )
        self.student = User.objects.create(
            name="Student", email="student@test.com",
            account_type=AccountType.STANDARD, is_activated=True,
        )
        self.course = Course.objects.create(
            owner=self.educator, name="AI Course", description="", is_published=True
        )
        self.course_settings = CourseSettings.objects.create(
            course=self.course,
            show_group_members_names=False,
            allow_students_to_create_groups=False,
            allow_students_to_delete_groups=False,
            allow_students_to_join_groups=False,
            allow_students_to_leave_groups=False,
            allow_students_to_modify_group_name=False,
            allow_students_to_add_or_remove_group_members=False,
            show_ai_score=False,  # default = hidden for students
        )
        self.teacher_membership = CourseMembership.objects.create(
            user=self.educator, course=self.course, role=Role.INSTRUCTOR
        )
        self.student_membership = CourseMembership.objects.create(
            user=self.student, course=self.course, role=Role.STUDENT
        )
        self.milestone = CourseMilestone.objects.create(
            course=self.course, name="M1", description="", is_published=True,
            start_date_time=tz.now(), end_date_time=tz.now() + timedelta(days=7),
        )
        self.form = Form.objects.create(name="Playtest Form")
        self.template = CourseMilestoneTemplate.objects.create(
            course=self.course, form=self.form, description="",
            submission_type=SubmissionType.INDIVIDUAL, is_published=True,
        )
        self.submission = CourseSubmission.objects.create(
            course=self.course, milestone=self.milestone, template=self.template,
            creator=self.student_membership, editor=self.student_membership,
            name="My Submission", description="", is_draft=False,
            submission_type=SubmissionType.INDIVIDUAL, form_response_data=[],
        )

    def call_create(self, idempotency_key=None, answer_content="answer v1",
                    score_json=None, **kwargs):
        return create_feedback_version_and_record(
            submission_id=self.submission.id,
            requester=self.student,
            question="gameplay_feedback",
            answer_content=answer_content,
            feedback_type=AIFeedbackRecord.FEEDBACK_TYPE_PLAYTEST,
            strategy=AIFeedbackRecord.STRATEGY_PLAYTEST,
            feedback_content="**Score: [80/100]** some text",
            idempotency_key=idempotency_key,
            score_json=score_json,
            model_version="test-model",
            token_usage_json={"prompt_tokens": 10, "completion_tokens": 5},
            latency_ms=123.4,
            genre="Strategy",
            mechanic="Resource management",
            **kwargs,
        )


class VersionTrackingTests(AIFeedbackBase):
    """Feature 1: version snapshots, version numbering, idempotency."""

    def test_versions_increment_per_student_question(self):
        r1 = self.call_create(idempotency_key=str(uuid.uuid4()), answer_content="first draft")
        r2 = self.call_create(idempotency_key=str(uuid.uuid4()), answer_content="second draft")

        self.assertEqual(r1.version.version_number, 1)
        self.assertEqual(r2.version.version_number, 2)
        self.assertEqual(FeedbackAnswerVersion.objects.count(), 2)
        self.assertEqual(AIFeedbackRecord.objects.count(), 2)

        # Snapshots capture the answer at the time of each trigger
        self.assertEqual(r1.version.answer_content, "first draft")
        self.assertEqual(r2.version.answer_content, "second draft")

    def test_idempotency_key_returns_existing_record(self):
        key = str(uuid.uuid4())
        r1 = self.call_create(idempotency_key=key, answer_content="same request")
        r2 = self.call_create(idempotency_key=key, answer_content="network retry")

        # Same logical request -> same record, no new version/record written
        self.assertEqual(r1.id, r2.id)
        self.assertEqual(AIFeedbackRecord.objects.count(), 1)
        self.assertEqual(FeedbackAnswerVersion.objects.count(), 1)

    def test_invalid_submission_raises_value_error(self):
        with self.assertRaises(ValueError):
            create_feedback_version_and_record(
                submission_id=999999,
                requester=self.student,
                question="q",
                answer_content="a",
                feedback_type=AIFeedbackRecord.FEEDBACK_TYPE_PLAYTEST,
                strategy=AIFeedbackRecord.STRATEGY_PLAYTEST,
                feedback_content="c",
            )

    def test_record_to_json_include_score_flag(self):
        record = self.call_create(
            idempotency_key=str(uuid.uuid4()), score_json={"score": 80}
        )

        full = ai_feedback_record_to_json(record)
        self.assertEqual(full["score_json"], {"score": 80})

        hidden = ai_feedback_record_to_json(record, include_score=False)
        self.assertIsNone(hidden["score_json"])

        # Other fields are unaffected when the score is hidden
        self.assertEqual(hidden["feedback_content"], record.feedback_content)
        self.assertEqual(hidden["version"]["version_number"], 1)


class ScoreVisibilityTests(AIFeedbackBase):
    """Feature 2: POST /api/feedback/records/ hides score_json for students when course disables show_ai_score."""

    def post_record(self, user, idempotency_key):
        client = jwt_client(user)
        return client.post(
            RECORDS_URL,
            {
                "submission_id": self.submission.id,
                "question": "gameplay_feedback",
                "initial_response": "my answer",
                "feedback_content": "**Score: [80/100]** some text",
                "genre": "Strategy",
                "mechanic": "Resource management",
                "idempotency_key": idempotency_key,
            },
            format="json",
        )

    def test_student_hides_score_when_course_disables(self):
        # Pre-create a record WITH a score (e.g. from the logic layer),
        # then have the student POST the same idempotency key -> hits the
        # idempotent return path, where include_score=False must strip it.
        key = str(uuid.uuid4())
        self.call_create(idempotency_key=key, score_json={"score": 80})

        resp = self.post_record(self.student, key)
        self.assertEqual(resp.status_code, 200)
        self.assertIsNone(resp.data["record"]["score_json"])

    def test_student_sees_score_when_course_enables(self):
        self.course_settings.show_ai_score = True
        self.course_settings.save()

        key = str(uuid.uuid4())
        self.call_create(idempotency_key=key, score_json={"score": 80})

        resp = self.post_record(self.student, key)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["record"]["score_json"], {"score": 80})

    def test_teacher_always_sees_score(self):
        key = str(uuid.uuid4())
        self.call_create(idempotency_key=key, score_json={"score": 80})

        resp = self.post_record(self.educator, key)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["record"]["score_json"], {"score": 80})

    def test_get_timeline_for_educator(self):
        self.call_create(idempotency_key=str(uuid.uuid4()), answer_content="v1")
        self.call_create(idempotency_key=str(uuid.uuid4()), answer_content="v2")

        client = jwt_client(self.educator)
        resp = client.get(
            RECORDS_URL,
            {"course_id": self.course.id, "user_id": self.student.id},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.data), 2)
        self.assertEqual([v["version_number"] for v in resp.data], [1, 2])
        # each version carries its feedback record(s)
        self.assertEqual(len(resp.data[0]["feedback_records"]), 1)

    def test_student_cannot_query_timeline(self):
        client = jwt_client(self.student)
        resp = client.get(RECORDS_URL, {"course_id": self.course.id})
        self.assertEqual(resp.status_code, 403)

    def test_standard_instructor_can_read_submission_timeline(self):
        """v1.6.0: a user invited as INSTRUCTOR keeps account_type=STANDARD, and
        must still be able to read the per-submission history (the frontend
        gates on the course role, so the backend must agree)."""
        invited = User.objects.create(
            name="Invited Teacher", email="invited@test.com",
            account_type=AccountType.STANDARD, is_activated=True,
        )
        CourseMembership.objects.create(
            user=invited, course=self.course, role=Role.INSTRUCTOR
        )
        self.call_create(idempotency_key=str(uuid.uuid4()), answer_content="v1")

        resp = jwt_client(invited).get(
            RECORDS_URL, {"submission_id": self.submission.id}
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.data), 1)
        self.assertEqual(resp.data[0]["version_number"], 1)
        self.assertEqual(len(resp.data[0]["feedback_records"]), 1)

    def test_standard_student_cannot_read_submission_timeline(self):
        """A STANDARD user without an instructor role anywhere still gets 403."""
        self.call_create(idempotency_key=str(uuid.uuid4()))

        resp = jwt_client(self.student).get(
            RECORDS_URL, {"submission_id": self.submission.id}
        )
        self.assertEqual(resp.status_code, 403)

    def test_standard_instructor_cannot_read_other_courses(self):
        """Being an instructor elsewhere must not expose another course's data."""
        other_course = Course.objects.create(
            owner=self.educator, name="Other Course", description="",
            is_published=True,
        )
        outsider = User.objects.create(
            name="Other Teacher", email="other@test.com",
            account_type=AccountType.STANDARD, is_activated=True,
        )
        CourseMembership.objects.create(
            user=outsider, course=other_course, role=Role.INSTRUCTOR
        )
        self.call_create(idempotency_key=str(uuid.uuid4()))

        resp = jwt_client(outsider).get(
            RECORDS_URL, {"submission_id": self.submission.id}
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data, [])


class CourseShowAiScoreTests(AIFeedbackBase):
    """Feature 2: course-level show_ai_score config."""

    def test_show_ai_score_defaults_to_false(self):
        fresh_course = Course.objects.create(
            owner=self.educator, name="Default Course", description="", is_published=True
        )
        fresh_settings = CourseSettings.objects.create(
            course=fresh_course,
            show_group_members_names=False,
            allow_students_to_create_groups=False,
            allow_students_to_delete_groups=False,
            allow_students_to_join_groups=False,
            allow_students_to_leave_groups=False,
            allow_students_to_modify_group_name=False,
            allow_students_to_add_or_remove_group_members=False,
        )
        self.assertFalse(fresh_settings.show_ai_score)


class BackfillTests(AIFeedbackBase):
    """Feature 1: legacy data backfill command."""

    def test_backfill_creates_v1_versions_and_is_idempotent(self):
        FeedbackInitialResponse.objects.create(
            course=self.course, milestone=self.milestone, template=self.template,
            creator=self.student_membership, name=str(self.template),
            question="gameplay_feedback", initial_response="legacy answer",
            genre="Strategy", mechanic="Resource management",
        )

        call_command("backfill_feedback_versions")

        versions = FeedbackAnswerVersion.objects.filter(
            creator=self.student_membership, question="gameplay_feedback"
        )
        self.assertEqual(versions.count(), 1)
        self.assertEqual(versions.first().version_number, 1)
        self.assertEqual(versions.first().answer_content, "legacy answer")

        # Running again must not duplicate
        call_command("backfill_feedback_versions")
        self.assertEqual(
            FeedbackAnswerVersion.objects.filter(
                creator=self.student_membership, question="gameplay_feedback"
            ).count(),
            1,
        )

    def test_backfill_skips_when_v1_already_exists(self):
        # A version created by the new feature path must not be overwritten
        self.call_create(idempotency_key=str(uuid.uuid4()), answer_content="new feature answer")

        call_command("backfill_feedback_versions")

        versions = FeedbackAnswerVersion.objects.filter(
            creator=self.student_membership, question="gameplay_feedback"
        )
        self.assertEqual(versions.count(), 1)
        self.assertEqual(versions.first().answer_content, "new feature answer")


class ProductionFailLoudlyTests(AIFeedbackBase):
    """AI providers unconfigured -> mock is DEBUG-only; production returns 503
    instead of serving simulated (score-less) feedback that could mislead."""

    FEEDBACK_URL = "/api/feedback/"

    def _feedback_post(self):
        client = jwt_client(self.educator)
        return client.post(
            self.FEEDBACK_URL,
            {
                "content": "my reflection",
                "submission_id": self.submission.id,
                "question": "gameplay_feedback",
            },
            format="json",
        )

    def test_feedback_503_without_key_in_production(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("OPENAI_API_KEY", None)
            with override_settings(DEBUG=False):
                resp = self._feedback_post()
        self.assertEqual(resp.status_code, 503)

    def test_feedback_mock_in_debug_has_no_scores(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("OPENAI_API_KEY", None)
            with override_settings(DEBUG=True):
                resp = self._feedback_post()
        self.assertEqual(resp.status_code, 200)
        self.assertIn("Professor Feedback", resp.data["feedback"])
        self.assertNotIn("Score", resp.data["feedback"])

    def test_playtest_503_without_lightrag_in_production(self):
        client = jwt_client(self.educator)
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("LIGHTRAG_URL", None)
            with override_settings(DEBUG=False):
                resp = client.post(
                    "/api/playtest/",
                    {"query": "x", "mode": "hybrid"},
                    format="json",
                )
        self.assertEqual(resp.status_code, 503)

    def test_playtest_mock_in_debug_has_no_scores(self):
        client = jwt_client(self.educator)
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("LIGHTRAG_URL", None)
            with override_settings(DEBUG=True):
                resp = client.post(
                    "/api/playtest/",
                    {"query": "x", "mode": "hybrid"},
                    format="json",
                )
        self.assertEqual(resp.status_code, 200)
        self.assertIn("Professor Feedback", resp.data["response"])
        self.assertNotIn("Score", resp.data["response"])
