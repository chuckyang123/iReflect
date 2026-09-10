"""
@changelog
| Version | Description                                            | Reference                                     |
| v1.0.0 | Initial implementation (indexed baseline)              |                                               |
| v1.1.0 | CourseView passes through show_ai_score (create/put) | REQ: 20260824-playtest-score-visibility TECH: tech-design §3.5 |
/@changelog

@author chuckyang123
"""
import logging
from collections import Counter

from django.db.models import Q, QuerySet, Prefetch
from django.utils.decorators import method_decorator
from django.views.decorators.cache import cache_control

from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.exceptions import PermissionDenied

from pigeonhole.common.constants import ROLE
from pigeonhole.common.parsers import parse_ms_timestamp_to_datetime
from pigeonhole.common.exceptions import BadRequest, InternalServerError
from users.middlewares import check_account_access
from users.models import User, AccountType
from .models import (
    Course,
    CourseGroup,
    CourseGroupMember,
    CourseMembership,
    CourseMilestone,
    CourseMilestoneTemplate,
    CourseSubmission,
    CourseSubmissionComment,
    PatchCourseGroupAction,
    Role,
)
from .logic import (
    batch_update_course_group_members,
    batch_update_course_submission_viewable_groups,
    can_create_course_group,
    can_delete_course_group,
    can_delete_course_submission,
    can_delete_course_submission_comment,
    can_update_course_group,
    can_update_course_submission,
    can_update_course_submission_comment,
    can_view_course_group_members,
    can_view_course_milestone_template,
    can_view_course_submission,
    course_group_to_json,
    course_group_with_members_to_json,
    course_membership_to_json,
    course_milestone_template_to_json,
    course_submission_comment_to_json,
    course_submission_summary_to_json,
    course_submission_to_json,
    course_summary_to_json,
    course_to_json,
    course_milestone_to_json,
    create_course,
    create_course_group,
    create_course_membership,
    create_course_milestone_template,
    create_course_submission,
    create_course_submission_comment,
    delete_course_submission_comment,
    get_requested_course_submissions,
    get_course_submission_comments,
    is_group_member,
    update_course,
    create_course_milestone,
    update_course_group,
    update_course_group_members,
    update_course_milestone,
    update_course_membership,
    update_course_milestone_template,
    update_course_submission,
    update_course_submission_comment,
)
from .serializers import (
    BatchMembershipCreationSerializer,
    CourseMemberCreationDataSerializer,
    GetCourseGroupSerializer,
    GetCourseSubmissionSerializer,
    PatchCourseGroupSerializer,
    PostCourseGroupSerializer,
    PostCourseMilestoneTemplateSerializer,
    PostCourseSerializer,
    PostCourseSubmissionCommentSerializer,
    PostCourseSubmissionSerializer,
    PutCourseMilestoneTemplateSerializer,
    PutCourseSerializer,
    PostCourseMilestoneSerializer,
    PutCourseMilestoneSerializer,
    PostCourseMembershipSerializer,
    PatchCourseMembershipSerializer,
    PutCourseSubmissionCommentSerializer,
    PutCourseSubmissionSerializer,
    PutCourseSubmissionViewableGroupsSerializer,
)
from .middlewares import (
    check_course,
    check_group,
    check_membership,
    check_requester_membership,
    check_milestone,
    check_submission,
    check_submission_comment,
    check_template,
)

logger = logging.getLogger("main")

# Create your views here.
class MyCoursesView(APIView):
    @method_decorator(cache_control(no_cache=True))
    @check_account_access(AccountType.STANDARD, AccountType.EDUCATOR, AccountType.ADMIN)
    def get(self, request, requester: User):
        ## only show courses which are published or if course membership role is above STUDENT
        visible_memberships: QuerySet[
            CourseMembership
        ] = requester.coursemembership_set.filter(
            ~Q(role=Role.STUDENT) | Q(course__is_published=True)
        ).select_related(
            "course__owner__profile_image"
        )

        data = [
            course_summary_to_json(course=membership.course, membership=membership)
            for membership in visible_memberships
        ]

        return Response(data=data, status=status.HTTP_200_OK)

    @check_account_access(AccountType.EDUCATOR, AccountType.ADMIN)
    def post(self, request, requester: User):
        serializer = PostCourseSerializer(data=request.data)

        serializer.is_valid(raise_exception=True)
        validated_data = serializer.validated_data

        new_course, new_membership = create_course(
            owner=requester,
            name=validated_data["name"],
            description=validated_data["description"],
            is_published=validated_data["is_published"],
            show_group_members_names=validated_data["show_group_members_names"],
            allow_students_to_create_groups=validated_data[
                "allow_students_to_create_groups"
            ],
            allow_students_to_delete_groups=validated_data[
                "allow_students_to_delete_groups"
            ],
            allow_students_to_join_groups=validated_data[
                "allow_students_to_join_groups"
            ],
            allow_students_to_leave_groups=validated_data[
                "allow_students_to_leave_groups"
            ],
            allow_students_to_modify_group_name=validated_data[
                "allow_students_to_modify_group_name"
            ],
            allow_students_to_add_or_remove_group_members=validated_data[
                "allow_students_to_add_or_remove_group_members"
            ],
            milestone_alias=validated_data["milestone_alias"],
            show_ai_score=validated_data["show_ai_score"],
        )

        data = course_summary_to_json(course=new_course, membership=new_membership)

        return Response(data=data, status=status.HTTP_201_CREATED)


class SingleCourseView(APIView):
    @method_decorator(cache_control(no_cache=True))
    @check_account_access(AccountType.STANDARD, AccountType.EDUCATOR, AccountType.ADMIN)
    @check_course
    @check_requester_membership(Role.STUDENT, Role.INSTRUCTOR, Role.CO_OWNER)
    def get(
        self,
        request,
        requester: User,
        course: Course,
        requester_membership: CourseMembership,
    ):
        data = course_to_json(course=course, membership=requester_membership)

        return Response(data=data, status=status.HTTP_200_OK)

    @check_account_access(AccountType.STANDARD, AccountType.EDUCATOR, AccountType.ADMIN)
    @check_course
    @check_requester_membership(Role.CO_OWNER)
    def put(
        self,
        request,
        requester: User,
        course: Course,
        requester_membership: CourseMembership,
    ):
        serializer = PutCourseSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        validated_data = serializer.validated_data

        owner_id = validated_data.get("owner_id")

        ## only course owner can update owner
        if owner_id is not None and course.owner != requester:
            raise PermissionDenied()

        try:
            updated_course = update_course(
                course=course,
                owner_id=owner_id,
                name=validated_data["name"],
                description=validated_data["description"],
                is_published=validated_data["is_published"],
                show_group_members_names=validated_data["show_group_members_names"],
                allow_students_to_create_groups=validated_data[
                    "allow_students_to_create_groups"
                ],
                allow_students_to_delete_groups=validated_data[
                    "allow_students_to_delete_groups"
                ],
                allow_students_to_join_groups=validated_data[
                    "allow_students_to_join_groups"
                ],
                allow_students_to_leave_groups=validated_data[
                    "allow_students_to_leave_groups"
                ],
                allow_students_to_modify_group_name=validated_data[
                    "allow_students_to_modify_group_name"
                ],
                allow_students_to_add_or_remove_group_members=validated_data[
                    "allow_students_to_add_or_remove_group_members"
                ],
                milestone_alias=validated_data["milestone_alias"],
                show_ai_score=validated_data["show_ai_score"],
            )
        except ValueError as e:
            raise BadRequest(detail=e)

        data = course_to_json(course=updated_course, membership=requester_membership)

        return Response(data=data, status=status.HTTP_200_OK)

    @check_account_access(AccountType.STANDARD, AccountType.EDUCATOR, AccountType.ADMIN)
    @check_course
    @check_requester_membership(Role.CO_OWNER)
    def delete(
        self,
        request,
        requester: User,
        course: Course,
        requester_membership: CourseMembership,
    ):
        ## only course owner can delete course
        if course.owner != requester:
            raise PermissionDenied()

        data = course_to_json(course=course, membership=requester_membership)

        course.delete()

        return Response(data=data, status=status.HTTP_200_OK)


class CourseMilestonesView(APIView):
    @method_decorator(cache_control(no_cache=True))
    @check_account_access(AccountType.STANDARD, AccountType.EDUCATOR, AccountType.ADMIN)
    @check_course
    @check_requester_membership(Role.STUDENT, Role.INSTRUCTOR, Role.CO_OWNER)
    def get(
        self,
        request,
        requester: User,
        course: Course,
        requester_membership: CourseMembership,
    ):
        visible_milestones: QuerySet[CourseMilestone] = course.coursemilestone_set.all()

        if requester_membership.role == Role.STUDENT:
            visible_milestones = visible_milestones.filter(is_published=True)

        data = [course_milestone_to_json(milestone) for milestone in visible_milestones]

        return Response(data=data, status=status.HTTP_200_OK)

    @check_account_access(AccountType.STANDARD, AccountType.EDUCATOR, AccountType.ADMIN)
    @check_course
    @check_requester_membership(Role.INSTRUCTOR, Role.CO_OWNER)
    def post(
        self,
        request,
        requester: User,
        course: Course,
        requester_membership: CourseMembership,
    ):
        serializer = PostCourseMilestoneSerializer(data=request.data)

        serializer.is_valid(raise_exception=True)
        validated_data = serializer.validated_data

        try:
            new_milestone = create_course_milestone(
                course=course,
                name=validated_data["name"],
                description=validated_data["description"],
                start_date_time=parse_ms_timestamp_to_datetime(
                    validated_data["start_date_time"]
                ),
                end_date_time=parse_ms_timestamp_to_datetime(
                    validated_data["end_date_time"]
                ),
                is_published=validated_data["is_published"],
            )
        except ValueError as e:
            raise BadRequest(detail=e)

        data = course_milestone_to_json(new_milestone)

        return Response(data=data, status=status.HTTP_201_CREATED)


class SingleCourseMilestoneView(APIView):
    @method_decorator(cache_control(no_cache=True))
    @check_account_access(AccountType.STANDARD, AccountType.EDUCATOR, AccountType.ADMIN)
    @check_course
    @check_requester_membership(Role.STUDENT, Role.INSTRUCTOR, Role.CO_OWNER)
    @check_milestone
    def get(
        self,
        request,
        requester: User,
        course: Course,
        requester_membership: CourseMembership,
        milestone: CourseMilestone,
    ):
        if requester_membership.role == Role.STUDENT and not milestone.is_published:
            raise PermissionDenied()

        data = course_milestone_to_json(milestone)

        return Response(data=data, status=status.HTTP_200_OK)

    @check_account_access(AccountType.STANDARD, AccountType.EDUCATOR, AccountType.ADMIN)
    @check_course
    @check_requester_membership(Role.INSTRUCTOR, Role.CO_OWNER)
    @check_milestone
    def put(
        self,
        request,
        requester: User,
        course: Course,
        requester_membership: CourseMembership,
        milestone: CourseMilestone,
    ):
        serializer = PutCourseMilestoneSerializer(data=request.data)

        serializer.is_valid(raise_exception=True)
        validated_data = serializer.validated_data

        updated_milestone = update_course_milestone(
            milestone=milestone,
            name=validated_data["name"],
            description=validated_data["description"],
            start_date_time=parse_ms_timestamp_to_datetime(
                validated_data["start_date_time"]
            ),
            end_date_time=parse_ms_timestamp_to_datetime(
                validated_data["end_date_time"]
            ),
            is_published=validated_data["is_published"],
        )

        data = course_milestone_to_json(updated_milestone)

        return Response(data=data, status=status.HTTP_200_OK)

    @check_account_access(AccountType.STANDARD, AccountType.EDUCATOR, AccountType.ADMIN)
    @check_course
    @check_requester_membership(Role.INSTRUCTOR, Role.CO_OWNER)
    @check_milestone
    def delete(
        self,
        request,
        requester: User,
        course: Course,
        requester_membership: CourseMembership,
        milestone: CourseMilestone,
    ):
        data = course_milestone_to_json(milestone)

        milestone.delete()

        return Response(data=data, status=status.HTTP_200_OK)


class CourseMembershipsView(APIView):
    @method_decorator(cache_control(no_cache=True))
    @check_account_access(AccountType.STANDARD, AccountType.EDUCATOR, AccountType.ADMIN)
    @check_course
    @check_requester_membership(Role.STUDENT, Role.INSTRUCTOR, Role.CO_OWNER)
    def get(
        self,
        request,
        requester: User,
        course: Course,
        requester_membership: CourseMembership,
    ):
        memberships: QuerySet[
            CourseMembership
        ] = course.coursemembership_set.select_related("user__profile_image")

        data = [course_membership_to_json(membership) for membership in memberships]

        return Response(data=data, status=status.HTTP_200_OK)

    @check_account_access(AccountType.STANDARD, AccountType.EDUCATOR, AccountType.ADMIN)
    @check_course
    @check_requester_membership(Role.CO_OWNER)
    def post(
        self,
        request,
        requester: User,
        course: Course,
        requester_membership: CourseMembership,
    ):
        serializer = PostCourseMembershipSerializer(data=request.data)

        serializer.is_valid(raise_exception=True)
        validated_data = serializer.validated_data

        try:
            new_membership = create_course_membership(
                user_id=validated_data["user_id"],
                course=course,
                role=validated_data["role"],
            )
        except ValueError as e:
            raise BadRequest(detail=e)

        data = course_membership_to_json(new_membership)

        return Response(data=data, status=status.HTTP_201_CREATED)


class SingleCourseMembershipView(APIView):
    @check_account_access(AccountType.STANDARD, AccountType.EDUCATOR, AccountType.ADMIN)
    @check_course
    @check_requester_membership(Role.CO_OWNER)
    @check_membership
    def patch(
        self,
        request,
        requester: User,
        course: Course,
        requester_membership: CourseMembership,
        membership: CourseMembership,
    ):
        ## cannot update owner membership or self update membership
        if course.owner == membership.user or requester_membership == membership:
            raise PermissionDenied()

        serializer = PatchCourseMembershipSerializer(data=request.data)

        serializer.is_valid(raise_exception=True)
        validated_data = serializer.validated_data

        updated_membership = update_course_membership(
            membership=membership, role=validated_data["role"]
        )

        data = course_membership_to_json(updated_membership)

        return Response(data=data, status=status.HTTP_200_OK)

    @check_account_access(AccountType.STANDARD, AccountType.EDUCATOR, AccountType.ADMIN)
    @check_course
    @check_requester_membership(Role.CO_OWNER)
    @check_membership
    def delete(
        self,
        request,
        requester: User,
        course: Course,
        requester_membership: CourseMembership,
        membership: CourseMembership,
    ):
        ## cannot delete owner or self delete membership
        if course.owner == membership.user or requester_membership == membership:
            raise PermissionDenied()

        data = course_membership_to_json(membership)

        membership.delete()

        return Response(data=data, status=status.HTTP_200_OK)


class CourseGroupsView(APIView):
    @method_decorator(cache_control(no_cache=True))
    @check_account_access(AccountType.STANDARD, AccountType.EDUCATOR, AccountType.ADMIN)
    @check_course
    @check_requester_membership(Role.STUDENT, Role.INSTRUCTOR, Role.CO_OWNER)
    def get(
        self,
        request,
        requester: User,
        course: Course,
        requester_membership: CourseMembership,
    ):
        serializer = GetCourseGroupSerializer(data=request.query_params.dict())

        serializer.is_valid(raise_exception=True)
        should_show_only_my_groups = serializer.validated_data["me"]

        ## prefetch related is used for performance optimization
        ## reference: https://betterprogramming.pub/django-select-related-and-prefetch-related-f23043fd635d
        groups: QuerySet[CourseGroup] = course.coursegroup_set.prefetch_related(
            Prefetch(
                lookup="coursegroupmember_set",
                queryset=CourseGroupMember.objects.select_related(
                    "member__user__profile_image"
                ),
            )
        )

        data = [
            course_group_with_members_to_json(group)
            if can_view_course_group_members(
                course=course, membership=requester_membership, group=group
            )
            else course_group_to_json(group)
            for group in groups
            if (
                not should_show_only_my_groups
                or is_group_member(membership=requester_membership, group=group)
            )
        ]

        return Response(data=data, status=status.HTTP_200_OK)

    @check_account_access(AccountType.STANDARD, AccountType.EDUCATOR, AccountType.ADMIN)
    @check_course
    @check_requester_membership(Role.STUDENT, Role.INSTRUCTOR, Role.CO_OWNER)
    def post(
        self,
        request,
        requester: User,
        course: Course,
        requester_membership: CourseMembership,
    ):
        if not can_create_course_group(course=course, membership=requester_membership):
            raise PermissionDenied()

        serializer = PostCourseGroupSerializer(data=request.data)

        serializer.is_valid(raise_exception=True)
        validated_data = serializer.validated_data

        try:
            new_group = create_course_group(course=course, name=validated_data["name"])
        except ValueError as e:
            raise BadRequest(detail=e)

        data = course_group_to_json(new_group)

        return Response(data=data, status=status.HTTP_201_CREATED)


class SingleCourseGroupView(APIView):
    @method_decorator(cache_control(no_cache=True))
    @check_account_access(AccountType.STANDARD, AccountType.EDUCATOR, AccountType.ADMIN)
    @check_course
    @check_requester_membership(Role.STUDENT, Role.INSTRUCTOR, Role.CO_OWNER)
    @check_group
    def get(
        self,
        request,
        requester: User,
        course: Course,
        requester_membership: CourseMembership,
        group: CourseGroup,
    ):
        data = (
            course_group_with_members_to_json(group)
            if can_view_course_group_members(
                course=course, membership=requester_membership, group=group
            )
            else course_group_to_json(group)
        )

        return Response(data=data, status=status.HTTP_200_OK)

    @check_account_access(AccountType.STANDARD, AccountType.EDUCATOR, AccountType.ADMIN)
    @check_course
    @check_requester_membership(Role.STUDENT, Role.INSTRUCTOR, Role.CO_OWNER)
    @check_group
    def patch(
        self,
        request,
        requester: User,
        course: Course,
        requester_membership: CourseMembership,
        group: CourseGroup,
    ):
        serializer = PatchCourseGroupSerializer(data=request.data)

        serializer.is_valid(raise_exception=True)
        validated_data = serializer.validated_data

        action = validated_data["action"]
        payload = validated_data["payload"]

        if not can_update_course_group(
            course=course, membership=requester_membership, group=group, action=action
        ):
            raise PermissionDenied()

        match action:
            case PatchCourseGroupAction.MODIFY:
                updated_course = update_course_group(group=group, name=payload["name"])
            case PatchCourseGroupAction.JOIN | PatchCourseGroupAction.LEAVE | PatchCourseGroupAction.ADD | PatchCourseGroupAction.REMOVE:
                try:
                    updated_course = update_course_group_members(
                        course=course,
                        requester_membership=requester_membership,
                        group=group,
                        user_id=payload["user_id"],
                        action=action,
                    )
                except ValueError as e:
                    logger.warning(e)
                    raise BadRequest(detail=e)
            case PatchCourseGroupAction.UPDATE_MEMBERS:
                try:

                    updated_course = batch_update_course_group_members(
                        course=course, group=group, user_ids=payload["user_ids"]
                    )

                except ValueError as e:
                    logger.warning(e)
                    raise BadRequest(detail=e)
            case _:  ## should never enter this case
                raise InternalServerError(detail="Invalid action.")

        data = course_group_with_members_to_json(updated_course)

        return Response(data=data, status=status.HTTP_200_OK)

    @check_account_access(AccountType.STANDARD, AccountType.EDUCATOR, AccountType.ADMIN)
    @check_course
    @check_requester_membership(Role.STUDENT, Role.INSTRUCTOR, Role.CO_OWNER)
    @check_group
    def delete(
        self,
        request,
        requester: User,
        course: Course,
        requester_membership: CourseMembership,
        group: CourseGroup,
    ):
        if not can_delete_course_group(
            course=course, membership=requester_membership, group=group
        ):
            raise PermissionDenied()

        data = course_group_with_members_to_json(group)

        group.delete()

        return Response(data=data, status=status.HTTP_200_OK)


class CourseMilestoneTemplatesView(APIView):
    @method_decorator(cache_control(no_cache=True))
    @check_account_access(AccountType.STANDARD, AccountType.EDUCATOR, AccountType.ADMIN)
    @check_course
    @check_requester_membership(Role.STUDENT, Role.INSTRUCTOR, Role.CO_OWNER)
    def get(
        self,
        request,
        requester: User,
        course: Course,
        requester_membership: CourseMembership,
    ):
        ## only show courses which are published or if course membership role is above STUDENT
        visible_templates: QuerySet[
            CourseMilestoneTemplate
        ] = course.coursemilestonetemplate_set.select_related("form")

        if requester_membership.role == Role.STUDENT:
            visible_templates = visible_templates.filter(is_published=True)

        data = [
            course_milestone_template_to_json(template)
            for template in visible_templates
        ]

        return Response(data=data, status=status.HTTP_200_OK)

    @check_account_access(AccountType.STANDARD, AccountType.EDUCATOR, AccountType.ADMIN)
    @check_course
    @check_requester_membership(Role.INSTRUCTOR, Role.CO_OWNER)
    def post(
        self,
        request,
        requester: User,
        course: Course,
        requester_membership: CourseMembership,
    ):
        serializer = PostCourseMilestoneTemplateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        validated_data = serializer.validated_data

        new_template = create_course_milestone_template(
            course=course,
            name=validated_data["name"],
            description=validated_data["description"],
            submission_type=validated_data["submission_type"],
            is_published=validated_data["is_published"],
            form_field_data=validated_data["form_field_data"],
        )

        data = course_milestone_template_to_json(new_template)

        return Response(data=data, status=status.HTTP_201_CREATED)


class SingleCourseMilestoneTemplateView(APIView):
    @method_decorator(cache_control(no_cache=True))
    @check_account_access(AccountType.STANDARD, AccountType.EDUCATOR, AccountType.ADMIN)
    @check_course
    @check_requester_membership(Role.STUDENT, Role.INSTRUCTOR, Role.CO_OWNER)
    @check_template
    def get(
        self,
        request,
        requester: User,
        course: Course,
        requester_membership: CourseMembership,
        template: CourseMilestoneTemplate,
    ):
        if not can_view_course_milestone_template(
            template=template, requester_membership=requester_membership
        ):
            raise PermissionDenied()

        data = course_milestone_template_to_json(template)

        return Response(data=data, status=status.HTTP_200_OK)

    @check_account_access(AccountType.STANDARD, AccountType.EDUCATOR, AccountType.ADMIN)
    @check_course
    @check_requester_membership(Role.INSTRUCTOR, Role.CO_OWNER)
    @check_template
    def put(
        self,
        request,
        requester: User,
        course: Course,
        requester_membership: CourseMembership,
        template: CourseMilestoneTemplate,
    ):
        serializer = PutCourseMilestoneTemplateSerializer(data=request.data)

        serializer.is_valid(raise_exception=True)
        validated_data = serializer.validated_data

        updated_template = update_course_milestone_template(
            template=template,
            name=validated_data["name"],
            description=validated_data["description"],
            submission_type=validated_data["submission_type"],
            is_published=validated_data["is_published"],
            form_field_data=validated_data["form_field_data"],
        )

        data = course_milestone_template_to_json(updated_template)

        return Response(data=data, status=status.HTTP_200_OK)

    @check_account_access(AccountType.STANDARD, AccountType.EDUCATOR, AccountType.ADMIN)
    @check_course
    @check_requester_membership(Role.INSTRUCTOR, Role.CO_OWNER)
    @check_template
    def delete(
        self,
        request,
        requester: User,
        course: Course,
        requester_membership: CourseMembership,
        template: CourseMilestoneTemplate,
    ):
        data = course_milestone_template_to_json(template)

        template.delete()

        return Response(data, status=status.HTTP_200_OK)


class CourseSubmissionsView(APIView):
    @method_decorator(cache_control(no_cache=True))
    @check_account_access(AccountType.STANDARD, AccountType.EDUCATOR, AccountType.ADMIN)
    @check_course
    @check_requester_membership(Role.STUDENT, Role.INSTRUCTOR, Role.CO_OWNER)
    def get(
        self,
        request,
        requester: User,
        course: Course,
        requester_membership: CourseMembership,
    ):
        serializer = GetCourseSubmissionSerializer(data=request.query_params.dict())

        serializer.is_valid(raise_exception=True)
        validated_data = serializer.validated_data

        submissions = get_requested_course_submissions(
            course=course,
            milestone_id=validated_data["milestone_id"],
            group_id=validated_data["group_id"],
            creator_id=validated_data["creator_id"],
            editor_id=validated_data["editor_id"],
            template_id=validated_data["template_id"],
        )

        full = validated_data["full"]

        data = [
            course_submission_to_json(submission=submission, with_comments=True)
            if full
            else course_submission_summary_to_json(submission)
            for submission in submissions
            if can_view_course_submission(
                requester_membership=requester_membership, submission=submission
            )
        ]

        return Response(data, status=status.HTTP_200_OK)

    @check_account_access(AccountType.STANDARD, AccountType.EDUCATOR, AccountType.ADMIN)
    @check_course
    @check_requester_membership(Role.STUDENT, Role.INSTRUCTOR, Role.CO_OWNER)
    def post(
        self,
        request,
        requester: User,
        course: Course,
        requester_membership: CourseMembership,
    ):
        serializer = PostCourseSubmissionSerializer(data=request.data)

        serializer.is_valid(raise_exception=True)
        validated_data = serializer.validated_data

        try:
            new_submission = create_course_submission(
                course=course,
                requester_membership=requester_membership,
                milestone_id=validated_data["milestone_id"],
                group_id=validated_data["group_id"],
                template_id=validated_data["template_id"],
                name=validated_data["name"],
                description=validated_data["description"],
                is_draft=validated_data["is_draft"],
                submission_type=validated_data["submission_type"],
                form_response_data=validated_data["form_response_data"],
            )
        except ValueError as e:
            raise BadRequest(detail=e)

        data = course_submission_to_json(new_submission)

        return Response(data=data, status=status.HTTP_201_CREATED)


class SingleCourseSubmissionView(APIView):
    @method_decorator(cache_control(no_cache=True))
    @check_account_access(AccountType.STANDARD, AccountType.EDUCATOR, AccountType.ADMIN)
    @check_course
    @check_requester_membership(Role.STUDENT, Role.INSTRUCTOR, Role.CO_OWNER)
    @check_submission
    def get(
        self,
        request,
        requester: User,
        course: Course,
        requester_membership: CourseMembership,
        submission: CourseSubmission,
    ):
        if not can_view_course_submission(
            requester_membership=requester_membership, submission=submission
        ):
            raise PermissionDenied()

        data = course_submission_to_json(submission)

        return Response(data=data, status=status.HTTP_200_OK)

    @check_account_access(AccountType.STANDARD, AccountType.EDUCATOR, AccountType.ADMIN)
    @check_course
    @check_requester_membership(Role.STUDENT, Role.INSTRUCTOR, Role.CO_OWNER)
    @check_submission
    def put(
        self,
        request,
        requester: User,
        course: Course,
        requester_membership: CourseMembership,
        submission: CourseSubmission,
    ):
        if not can_update_course_submission(
            requester_membership=requester_membership, submission=submission
        ):
            raise PermissionDenied()

        serializer = PutCourseSubmissionSerializer(data=request.data)

        serializer.is_valid(raise_exception=True)
        validated_data = serializer.validated_data

        try:
            updated_submission = update_course_submission(
                submission=submission,
                course=course,
                requester_membership=requester_membership,
                group_id=validated_data["group_id"],
                name=validated_data["name"],
                description=validated_data["description"],
                is_draft=validated_data["is_draft"],
                submission_type=validated_data["submission_type"],
                form_response_data=validated_data["form_response_data"],
            )
        except ValueError as e:
            raise BadRequest(detail=e)

        data = course_submission_to_json(updated_submission)

        return Response(data=data, status=status.HTTP_200_OK)

    @check_account_access(AccountType.STANDARD, AccountType.EDUCATOR, AccountType.ADMIN)
    @check_course
    @check_requester_membership(Role.STUDENT, Role.INSTRUCTOR, Role.CO_OWNER)
    @check_submission
    def delete(
        self,
        request,
        requester: User,
        course: Course,
        requester_membership: CourseMembership,
        submission: CourseSubmission,
    ):
        if not can_delete_course_submission(
            requester_membership=requester_membership, submission=submission
        ):
            raise PermissionDenied()

        data = course_submission_to_json(submission)

        submission.delete()

        return Response(data=data, status=status.HTTP_200_OK)


class CourseSubmissionFieldCommentsView(APIView):
    @method_decorator(cache_control(no_cache=True))
    @check_account_access(AccountType.STANDARD, AccountType.EDUCATOR, AccountType.ADMIN)
    @check_course
    @check_requester_membership(Role.STUDENT, Role.INSTRUCTOR, Role.CO_OWNER)
    @check_submission
    def get(
        self,
        request,
        requester: User,
        course: Course,
        requester_membership: CourseMembership,
        submission: CourseSubmission,
    ):
        if not can_view_course_submission(
            requester_membership=requester_membership, submission=submission
        ):
            raise PermissionDenied()

        field_to_comment_count_map = Counter(
            submission.coursesubmissioncomment_set.values_list("field_index", flat=True)
        )

        data = [
            field_to_comment_count_map[i]
            for i in range(len(submission.form_response_data))
        ]

        return Response(data=data, status=status.HTTP_200_OK)


class CourseSubmissionSingleFieldCommentsView(APIView):
    @method_decorator(cache_control(no_cache=True))
    @check_account_access(AccountType.STANDARD, AccountType.EDUCATOR, AccountType.ADMIN)
    @check_course
    @check_requester_membership(Role.STUDENT, Role.INSTRUCTOR, Role.CO_OWNER)
    @check_submission
    def get(
        self,
        request,
        requester: User,
        course: Course,
        requester_membership: CourseMembership,
        submission: CourseSubmission,
        field_index: int,
    ):
        if not can_view_course_submission(
            requester_membership=requester_membership, submission=submission
        ):
            raise PermissionDenied()

        if field_index < 0 or field_index >= len(submission.form_response_data):
            raise BadRequest(detail="No such field.")

        comments = get_course_submission_comments(submission).filter(
            field_index=field_index
        )

        data = [course_submission_comment_to_json(comment) for comment in comments]

        return Response(data=data, status=status.HTTP_200_OK)

    @check_account_access(AccountType.STANDARD, AccountType.EDUCATOR, AccountType.ADMIN)
    @check_course
    @check_requester_membership(Role.STUDENT, Role.INSTRUCTOR, Role.CO_OWNER)
    @check_submission
    def post(
        self,
        request,
        requester: User,
        course: Course,
        requester_membership: CourseMembership,
        submission: CourseSubmission,
        field_index: int,
    ):
        if not can_view_course_submission(
            requester_membership=requester_membership, submission=submission
        ):
            raise PermissionDenied()

        if field_index < 0 or field_index >= len(submission.form_response_data):
            raise BadRequest(detail="No such field.")

        serializer = PostCourseSubmissionCommentSerializer(data=request.data)

        serializer.is_valid(raise_exception=True)
        validated_data = serializer.validated_data

        new_comment = create_course_submission_comment(
            submission=submission,
            commenter=requester,
            content=validated_data["content"],
            field_index=field_index,
            member=requester_membership,
        )

        data = course_submission_comment_to_json(new_comment)

        return Response(data=data, status=status.HTTP_201_CREATED)


class SingleCourseSubmissionCommentView(APIView):
    @check_account_access(AccountType.STANDARD, AccountType.EDUCATOR, AccountType.ADMIN)
    @check_course
    @check_requester_membership(Role.STUDENT, Role.INSTRUCTOR, Role.CO_OWNER)
    @check_submission
    @check_submission_comment
    def patch(
        self,
        request,
        requester: User,
        course: Course,
        requester_membership: CourseMembership,
        submission: CourseSubmission,
        submission_comment: CourseSubmissionComment,
    ):

        if not can_update_course_submission_comment(
            requester_membership=requester_membership,
            submission_comment=submission_comment,
        ):
            raise PermissionDenied()

        if submission_comment.comment.is_deleted:
            raise BadRequest(detail="Cannot update deleted comment.")

        serializer = PutCourseSubmissionCommentSerializer(data=request.data)

        serializer.is_valid(raise_exception=True)
        validated_data = serializer.validated_data

        updated_comment = update_course_submission_comment(
            submission_comment=submission_comment,
            content=validated_data["content"],
        )

        data = course_submission_comment_to_json(updated_comment)

        return Response(data=data, status=status.HTTP_200_OK)

    @check_account_access(AccountType.STANDARD, AccountType.EDUCATOR, AccountType.ADMIN)
    @check_course
    @check_requester_membership(Role.STUDENT, Role.INSTRUCTOR, Role.CO_OWNER)
    @check_submission
    @check_submission_comment
    def delete(
        self,
        request,
        requester: User,
        course: Course,
        requester_membership: CourseMembership,
        submission: CourseSubmission,
        submission_comment: CourseSubmissionComment,
    ):

        if not can_delete_course_submission_comment(
            requester_membership=requester_membership,
            submission_comment=submission_comment,
        ):
            raise PermissionDenied()

        if submission_comment.comment.is_deleted:
            raise BadRequest(detail="Comment has already been deleted.")

        deleted_comment = delete_course_submission_comment(submission_comment)

        data = course_submission_comment_to_json(deleted_comment)

        return Response(data=data, status=status.HTTP_200_OK)


class CourseMembershipsWithNewUserCreationView(APIView):
    @check_account_access(AccountType.STANDARD, AccountType.EDUCATOR, AccountType.ADMIN)
    @check_course
    @check_requester_membership(Role.CO_OWNER)
    def post(
        self,
        request,
        requester: User,
        course: Course,
        requester_membership: CourseMembership,
    ):
        serializer = BatchMembershipCreationSerializer(data=request.data)

        serializer.is_valid(raise_exception=True)
        validated_data = serializer.validated_data

        new_members_data = list(
            filter(lambda data: "email" in data, validated_data["member_creation_data"])
        )
        emails = set(map(lambda data: data["email"], new_members_data))

        # get users that already exist
        existing_users = User.objects.filter(email__in=emails)
        existing_users_emails = set(existing_users.values_list("email", flat=True))

        new_users_data = [
            user_data
            for user_data in new_members_data
            if user_data["email"] not in existing_users_emails
        ]

        # create users that don't exist yet
        new_users_to_be_created = (
            User(
                email=user_data["email"],
                name="" if "name" not in user_data else user_data["name"],
            )
            for user_data in new_users_data
        )
        new_users = User.objects.bulk_create(new_users_to_be_created)

        all_users = list(existing_users) + new_users
        new_memberships_to_be_created = (
            CourseMembership(course=course, user=user) for user in all_users
        )
        CourseMembership.objects.bulk_create(
            new_memberships_to_be_created, ignore_conflicts=True
        )

        # return all members
        memberships = CourseMembership.objects.filter(user__email__in=emails)
        data = [course_membership_to_json(membership) for membership in memberships]

        return Response(data=data, status=status.HTTP_200_OK)


class CourseSubmissionViewableGroupsView(APIView):
    @method_decorator(cache_control(no_cache=True))
    @check_account_access(AccountType.STANDARD, AccountType.EDUCATOR, AccountType.ADMIN)
    @check_course
    @check_requester_membership(Role.INSTRUCTOR, Role.CO_OWNER)
    @check_submission
    def get(
        self,
        request,
        requester: User,
        course: Course,
        requester_membership: CourseMembership,
        submission: CourseSubmission,
    ):
        viewable_groups: QuerySet[CourseGroup] = submission.coursesubmissionviewablegroup_set.prefetch_related('group')

        data = [course_group_to_json(viewable_group.group) for viewable_group in viewable_groups]

        return Response(data=data, status=status.HTTP_200_OK)
    
    @check_account_access(AccountType.STANDARD, AccountType.EDUCATOR, AccountType.ADMIN)
    @check_course
    @check_requester_membership(Role.INSTRUCTOR, Role.CO_OWNER)
    @check_submission
    def put(
        self,
        request,
        requester: User,
        course: Course,
        requester_membership: CourseMembership,
        submission: CourseSubmission,
    ):
        serializer = PutCourseSubmissionViewableGroupsSerializer(data=request.data)

        serializer.is_valid(raise_exception=True)
        validated_data = serializer.validated_data

        try:
            updated_viewable_groups = batch_update_course_submission_viewable_groups(
                course=course, submission=submission, group_ids=validated_data["group_ids"]
            )
        except ValueError as e:
            raise BadRequest(detail=e)

        data = [
            course_group_to_json(viewable_group.group) 
            for viewable_group in updated_viewable_groups
        ]

        return Response(data=data, status=status.HTTP_200_OK)
