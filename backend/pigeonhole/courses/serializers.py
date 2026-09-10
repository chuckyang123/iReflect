"""
@changelog
| Version | Description                                            | Reference                                     |
| v1.0.0 | Initial implementation (indexed baseline)              |                                               |
| v1.1.0 | CourseSettingsSerializer adds show_ai_score (default=False) | REQ: 20260824-playtest-score-visibility TECH: tech-design §3.3 |
/@changelog

@author chuckyang123
"""
from rest_framework import serializers

from pigeonhole.common.models import MergeSerializersMixin
from pigeonhole.common.serializers import (
    NameSerializer,
    UserIdSerializer,
    IdField,
    ObjectListField,
    BatchUserIdSerializer,
)
from forms.serializers import FormSerializer

from .models import (
    Course,
    CourseGroup,
    CourseMembership,
    CourseMilestone,
    CourseMilestoneTemplate,
    CourseSettings,
    CourseSubmission,
    PatchCourseGroupAction,
    Role,
    Comment,
)


class CourseSettingsSerializer(serializers.ModelSerializer):
    ## need to override auto-generated one to make it required
    milestone_alias = serializers.CharField(
        required=True, max_length=255, allow_blank=True
    )
    ## default False so POST/PUT without this key still resolves (PRD 20260824)
    show_ai_score = serializers.BooleanField(required=False, default=False)

    class Meta:
        model = CourseSettings
        fields = (
            "show_group_members_names",
            "allow_students_to_create_groups",
            "allow_students_to_delete_groups",
            "allow_students_to_join_groups",
            "allow_students_to_leave_groups",
            "allow_students_to_modify_group_name",
            "allow_students_to_add_or_remove_group_members",
            "milestone_alias",
            "show_ai_score",
        )


class PostCourseSerializer(MergeSerializersMixin, serializers.ModelSerializer):
    ## need to override auto-generated one to make it required
    description = serializers.CharField(required=True, allow_blank=True)

    class Meta:
        model = Course
        fields = ("name", "description", "is_published")
        merge_serializers = (CourseSettingsSerializer,)


class PutCourseSerializer(PostCourseSerializer):
    owner_id = IdField(required=False)

    class Meta(PostCourseSerializer.Meta):
        fields = PostCourseSerializer.Meta.fields + ("owner_id",)


class PostCourseMilestoneSerializer(serializers.ModelSerializer):
    ## need to override auto-generated one to make it required
    description = serializers.CharField(required=True, allow_blank=True)
    start_date_time = serializers.IntegerField(required=True, min_value=0)
    end_date_time = serializers.IntegerField(
        required=True, allow_null=True, min_value=0
    )

    def validate(self, data):
        """
        Check that start_date_time is before end_date_time.
        """
        start_date_time = data["start_date_time"]
        end_date_time = data["end_date_time"]

        if end_date_time is not None and start_date_time >= end_date_time:
            raise serializers.ValidationError(
                "Start date/time must be before end date/time."
            )

        return data

    class Meta:
        model = CourseMilestone
        fields = (
            "name",
            "description",
            "start_date_time",
            "end_date_time",
            "is_published",
        )


PutCourseMilestoneSerializer = PostCourseMilestoneSerializer


class PostCourseMembershipSerializer(serializers.ModelSerializer):
    user_id = IdField(required=True)
    ## need to override auto-generated one to make it required
    role = serializers.ChoiceField(required=True, choices=Role.choices)

    class Meta:
        model = CourseMembership
        fields = ("role",)


class PatchCourseMembershipSerializer(serializers.ModelSerializer):
    ## need to override auto-generated one to make it required
    role = serializers.ChoiceField(required=True, choices=Role.choices)

    class Meta:
        model = CourseMembership
        fields = ("role",)


class GetCourseGroupSerializer(serializers.Serializer):
    me = serializers.BooleanField(required=False, default=False)


class PostCourseGroupSerializer(serializers.ModelSerializer):
    class Meta:
        model = CourseGroup
        fields = ("name",)


class PatchCourseGroupSerializer(serializers.Serializer):
    action = serializers.ChoiceField(
        required=True, choices=PatchCourseGroupAction.choices
    )
    payload = serializers.JSONField(required=True, allow_null=True)

    def validate(self, data):
        """
        Check the payload according to action
        """
        action = data["action"]
        payload = data["payload"]

        match action:
            case PatchCourseGroupAction.MODIFY:
                serializer = NameSerializer(data=payload)
                serializer.is_valid(raise_exception=True)
            case PatchCourseGroupAction.ADD | PatchCourseGroupAction.REMOVE:
                serializer = UserIdSerializer(data=payload)
                serializer.is_valid(raise_exception=True)
            case PatchCourseGroupAction.UPDATE_MEMBERS:
                serializer = BatchUserIdSerializer(data=payload)
                serializer.is_valid(raise_exception=True)

        return data


class PostCourseMilestoneTemplateSerializer(
    MergeSerializersMixin, serializers.ModelSerializer
):
    ## need to override auto-generated one to make it required
    description = serializers.CharField(required=True, allow_blank=True)

    class Meta:
        model = CourseMilestoneTemplate
        fields = ("description", "submission_type", "is_published")
        merge_serializers = (FormSerializer,)


PutCourseMilestoneTemplateSerializer = PostCourseMilestoneTemplateSerializer


class GetCourseSubmissionSerializer(serializers.Serializer):
    milestone_id = IdField(required=False, default=None)
    group_id = IdField(required=False, default=None)
    creator_id = IdField(required=False, default=None)
    editor_id = IdField(required=False, default=None)
    template_id = IdField(required=False, default=None)
    full = serializers.BooleanField(required=False, default=False)


# Serializer for requests to update course submission
class PutCourseSubmissionSerializer(serializers.ModelSerializer):
    group_id = IdField(required=True, allow_null=True)
    ## need to override auto-generated one to make it required
    description = serializers.CharField(required=True, allow_blank=True)
    form_response_data = ObjectListField(required=True)

    class Meta:
        model = CourseSubmission
        fields = (
            "group_id",
            "name",
            "description",
            "is_draft",
            "submission_type",
            "form_response_data",
        )


# Serializer for request to create new course submission
class PostCourseSubmissionSerializer(PutCourseSubmissionSerializer):
    milestone_id = IdField(required=True)
    template_id = IdField(required=True)

    class Meta(PutCourseSubmissionSerializer.Meta):
        fields = PutCourseSubmissionSerializer.Meta.fields + (
            "milestone_id",
            "template_id",
        )


class PostCourseSubmissionCommentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Comment
        fields = ("content",)


PutCourseSubmissionCommentSerializer = PostCourseSubmissionCommentSerializer


class CourseMemberCreationDataSerializer(serializers.Serializer):
    email = serializers.EmailField()
    name = serializers.CharField(max_length=255, allow_blank=True, required=False)


class BatchMembershipCreationSerializer(serializers.Serializer):
    member_creation_data = serializers.JSONField()

class PutCourseSubmissionViewableGroupsSerializer(serializers.Serializer):
    group_ids = serializers.ListField(child=IdField(required=True))
