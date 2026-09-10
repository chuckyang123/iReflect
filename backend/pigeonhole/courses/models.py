"""
@changelog
| Version | Description                                            | Reference                                     |
| v1.0.0 | Initial implementation (indexed baseline)              |                                               |
| v1.1.0 | Added CourseSettings.show_ai_score: controls student-facing AI score display | REQ: 20260824-playtest-score-visibility TECH: tech-design §3.1 |
/@changelog

@author chuckyang123
"""
from django.db import models
from django.db.models.signals import post_delete

from pigeonhole.common.utils import default_list
from pigeonhole.common.models import TimestampedModel
from forms.models import Form
from users.models import User


class Role(models.TextChoices):
    CO_OWNER = "CO-OWNER"
    INSTRUCTOR = "INSTRUCTOR"
    STUDENT = "STUDENT"


class SubmissionType(models.TextChoices):
    INDIVIDUAL = "INDIVIDUAL"
    GROUP = "GROUP"
    INDIVIDUAL_GROUP = "INDIVIDUAL/GROUP"


class PatchCourseGroupAction(models.TextChoices):
    JOIN = "JOIN"
    LEAVE = "LEAVE"
    MODIFY = "MODIFY"
    ADD = "ADD"
    REMOVE = "REMOVE"
    UPDATE_MEMBERS = "UPDATE_MEMBERS"


MAX_ROLE_LENGTH = max(map(len, Role))
MAX_SUBMISSION_TYPE_LENGTH = max(map(len, SubmissionType))

# Create your models here.
class Course(TimestampedModel):
    owner = models.ForeignKey(User, on_delete=models.CASCADE)
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    is_published = models.BooleanField()

    def __str__(self) -> str:
        return f"{self.name} | {self.owner}"


## Table extension of Course
## Only owner and co-owner can modify
class CourseSettings(TimestampedModel):
    course = models.OneToOneField(Course, on_delete=models.CASCADE)
    show_group_members_names = models.BooleanField()
    allow_students_to_create_groups = models.BooleanField()
    allow_students_to_delete_groups = models.BooleanField()
    allow_students_to_join_groups = models.BooleanField()
    allow_students_to_leave_groups = models.BooleanField()
    allow_students_to_modify_group_name = models.BooleanField()
    allow_students_to_add_or_remove_group_members = models.BooleanField()
    milestone_alias = models.CharField(max_length=255, blank=True)
    show_ai_score = models.BooleanField(
        default=False,
        help_text=(
            "If False (default), students only see AI text suggestions, "
            "not numeric scores (score_json). Teachers always see scores."
        ),
    )

    class Meta:
        verbose_name_plural = "course settings"

    def __str__(self) -> str:
        return f"{self.course}"


class CourseMembership(TimestampedModel):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    course = models.ForeignKey(Course, on_delete=models.CASCADE)
    role = models.CharField(
        max_length=MAX_ROLE_LENGTH, choices=Role.choices, default=Role.STUDENT
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user_id", "course_id"], name="unique_course_membership"
            )
        ]

    def __str__(self) -> str:
        return f"{self.user} | {self.role} | {self.course.name}"


class CourseGroup(TimestampedModel):
    course = models.ForeignKey(Course, on_delete=models.CASCADE)
    name = models.CharField(max_length=255)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["course_id", "name"], name="unique_course_group_name"
            )
        ]

    def __str__(self) -> str:
        return f"{self.name} | {self.course.name}"


class CourseGroupMember(TimestampedModel):
    member = models.ForeignKey(CourseMembership, on_delete=models.CASCADE)
    group = models.ForeignKey(CourseGroup, on_delete=models.CASCADE)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["member_id", "group_id"],
                name="unique_course_group_member",
            )
        ]

    def __str__(self) -> str:
        return f"{self.group.name} | {self.member}"


class CourseMilestone(TimestampedModel):
    course = models.ForeignKey(Course, on_delete=models.CASCADE)
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    start_date_time = models.DateTimeField()
    end_date_time = models.DateTimeField(blank=True, null=True)
    is_published = models.BooleanField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["course_id", "name"],
                name="unique_course_milestone_name",
            ),
            ## CHECK constraint will pass even if expression evaluates to unknown/null
            models.CheckConstraint(
                check=models.Q(start_date_time__lt=models.F("end_date_time")),
                name="course_milestone_start_date_time_lt_end_date_time",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.name} | {self.course.name}"


class CourseMilestoneTemplate(TimestampedModel):
    course = models.ForeignKey(Course, on_delete=models.CASCADE)
    form = models.OneToOneField(Form, on_delete=models.CASCADE)
    description = models.TextField(blank=True)
    submission_type = models.CharField(
        max_length=MAX_SUBMISSION_TYPE_LENGTH, choices=SubmissionType.choices
    )
    is_published = models.BooleanField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["course_id", "form_id"],
                name="unique_course_form",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.form.name} | {self.course.name}"


def course_milestone_template_cleanup(
    sender, instance: CourseMilestoneTemplate, **kwargs
):
    if not instance.form:
        return

    instance.form.delete()


## set up listener to delete form when a course milestone template is deleted
post_delete.connect(
    course_milestone_template_cleanup,
    sender=CourseMilestoneTemplate,
    dispatch_uid="courses.course_milestone_template.course_milestone_template_cleanup",
)


class CourseSubmission(TimestampedModel):
    ## ensure there are no "lost" submissions if creator is removed from the course
    course = models.ForeignKey(Course, on_delete=models.CASCADE)
    milestone = models.ForeignKey(CourseMilestone, on_delete=models.SET_NULL, null=True)
    group = models.ForeignKey(
        CourseGroup, on_delete=models.SET_NULL, blank=True, null=True
    )
    template = models.ForeignKey(
        CourseMilestoneTemplate, on_delete=models.SET_NULL, null=True
    )
    creator = models.ForeignKey(CourseMembership, on_delete=models.SET_NULL, null=True)
    editor = models.ForeignKey(
        CourseMembership, on_delete=models.SET_NULL, null=True, related_name="+"
    )
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    is_draft = models.BooleanField()
    submission_type = models.CharField(
        max_length=MAX_SUBMISSION_TYPE_LENGTH, choices=SubmissionType.choices
    )
    form_response_data = models.JSONField(blank=True, default=default_list)

    def __str__(self) -> str:
        return f"{self.name} | {self.creator}"


class CourseSubmissionViewableGroup(TimestampedModel):
    submission = models.ForeignKey(CourseSubmission, on_delete=models.CASCADE)
    group = models.ForeignKey(CourseGroup, on_delete=models.CASCADE)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["submission_id", "group_id"],
                name="unique_submission_viewable_group",
            )
        ]

    def __str__(self) -> str:
        return f"{self.submission.name} | {self.group}"


class CourseSubmissionViewableMember(TimestampedModel):
    submission = models.ForeignKey(CourseSubmission, on_delete=models.CASCADE)
    member = models.ForeignKey(CourseMembership, on_delete=models.CASCADE)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["submission_id", "member_id"],
                name="unique_submission_viewable_member",
            )
        ]

    def __str__(self) -> str:
        return f"{self.submission.name} | {self.member}"


class Comment(TimestampedModel):
    content = models.TextField()
    is_deleted = models.BooleanField(default=False)
    commenter = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)

    def __str__(self) -> str:
        return f"{self.created_at} | {self.commenter}"


class CourseSubmissionComment(TimestampedModel):
    submission = models.ForeignKey(CourseSubmission, on_delete=models.CASCADE)
    comment = models.OneToOneField(Comment, on_delete=models.CASCADE)
    field_index = models.PositiveIntegerField()
    member = models.ForeignKey(CourseMembership, on_delete=models.SET_NULL, null=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["submission_id", "comment_id"],
                name="unique_submission_comment",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.submission.name} | {self.comment}"


def course_submission_comment_cleanup(
    sender, instance: CourseSubmissionComment, **kwargs
):
    if not instance.comment:
        return

    instance.comment.delete()


class VisibilityStatus(models.TextChoices):
    PRIVATE = "PRIVATE"
    PUBLISHED = "PUBLISHED"


## set up listener to delete comment when a course submission comment is deleted
post_delete.connect(
    course_submission_comment_cleanup,
    sender=CourseSubmissionComment,
    dispatch_uid="courses.course_submission_comment.course_submission_comment_cleanup",
)
