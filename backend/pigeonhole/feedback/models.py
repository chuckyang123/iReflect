"""
@changelog
| Version | Description                                      | Reference                                   |
| v1.0.0  | Initial implementation: FeedbackInitialResponse model for collecting feedback initial responses |                                             |
| v1.1.0  | Added FeedbackAnswerVersion and AIFeedbackRecord: | REQ: 20260818-feedback-modification-tracking |
|         | answer version snapshots + AI feedback record persistence | TECH: 04_design_tech-design.md §3.2          |
| v1.2.0  | FeedbackAnswerVersion.submission FK for per-submission history filtering | REQ: 20260818-feedback-modification-tracking |
|         |                                                     | TECH: 04_design_tech-design.md §3.2          |
/@changelog

@author chuckyang123
"""
from django.db import models

from pigeonhole.common.models import TimestampedModel
from courses.models import (
    Course,
    CourseMilestone,
    CourseMilestoneTemplate,
    CourseGroup,
    CourseMembership,
    CourseSubmission,
)
from users.models import User

# Model for initial responses to the feedback feature
class FeedbackInitialResponse(TimestampedModel):
    course = models.ForeignKey(Course, on_delete=models.CASCADE)
    milestone = models.ForeignKey(CourseMilestone, on_delete=models.SET_NULL, null=True)
    template = models.ForeignKey(
        CourseMilestoneTemplate, on_delete=models.SET_NULL, null=True
    )
    creator = models.ForeignKey(CourseMembership, on_delete=models.SET_NULL, null=True)
    name = models.CharField(max_length=255)
    question = models.CharField(max_length=1000)
    initial_response = models.TextField(blank=False)
    genre = models.TextField(null=True, blank=True)
    mechanic = models.TextField(null=True, blank=True)

    class Meta:
        unique_together = ('course', 'milestone', 'template', 'creator', 'question')

    def __str__(self) -> str:
        return f"{self.name} | {self.creator} | {self.question}"


class FeedbackAnswerVersion(TimestampedModel):
    """Answer version table: snapshots the student's answer each time AI feedback is triggered, forming a modification timeline."""
    course = models.ForeignKey(Course, on_delete=models.CASCADE)
    milestone = models.ForeignKey(CourseMilestone, on_delete=models.SET_NULL, null=True)
    template = models.ForeignKey(
        CourseMilestoneTemplate, on_delete=models.SET_NULL, null=True
    )
    submission = models.ForeignKey(
        CourseSubmission,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="feedback_answer_versions",
    )
    creator = models.ForeignKey(CourseMembership, on_delete=models.SET_NULL, null=True)
    name = models.CharField(max_length=255)
    question = models.CharField(max_length=1000)
    answer_content = models.TextField(blank=False)
    version_number = models.PositiveIntegerField()
    genre = models.TextField(null=True, blank=True)
    mechanic = models.TextField(null=True, blank=True)

    class Meta:
        # Version number is unique per student/question so the timeline can be reconstructed
        unique_together = (
            'course', 'milestone', 'template', 'creator', 'question', 'version_number',
        )

    def __str__(self) -> str:
        return f"{self.name} | {self.creator} | {self.question} | v{self.version_number}"


class AIFeedbackRecord(TimestampedModel):
    """AI feedback record table: one row per generated feedback, linked to the triggering answer version."""
    FEEDBACK_TYPE_REFLECTION = "REFLECTION"
    FEEDBACK_TYPE_PLAYTEST = "PLAYTEST"
    FEEDBACK_TYPE_CHOICES = [
        (FEEDBACK_TYPE_REFLECTION, "Reflection writing feedback"),
        (FEEDBACK_TYPE_PLAYTEST, "Playtest feedback"),
    ]

    STRATEGY_BASIC = "BASIC"
    STRATEGY_ADVANCED = "ADVANCED"
    STRATEGY_PLAYTEST = "PLAYTEST"
    STRATEGY_CHOICES = [
        (STRATEGY_BASIC, "Basic prompt"),
        (STRATEGY_ADVANCED, "Advanced prompt"),
        (STRATEGY_PLAYTEST, "Playtest (LightRAG)"),
    ]

    version = models.ForeignKey(
        FeedbackAnswerVersion, on_delete=models.CASCADE, related_name="feedback_records"
    )
    feedback_type = models.CharField(max_length=20, choices=FEEDBACK_TYPE_CHOICES)
    strategy = models.CharField(max_length=20, choices=STRATEGY_CHOICES)
    score_json = models.JSONField(null=True, blank=True)
    feedback_content = models.TextField(blank=False)
    model_version = models.CharField(max_length=255, blank=True, default="")
    token_usage_json = models.JSONField(null=True, blank=True)
    latency_ms = models.FloatField(null=True, blank=True)
    # Idempotency key: the frontend sends a UUID per request to prevent duplicate records from network retries (RISK-DA006)
    idempotency_key = models.UUIDField(null=True, blank=True, unique=True)

    def __str__(self) -> str:
        return f"{self.feedback_type} | {self.strategy} | version {self.version_id}"
