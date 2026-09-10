"""
@changelog
| Version | Description                                            | Reference                                     |
| v1.0.0 | Initial implementation (indexed baseline)              |                                               |
| v1.1.0 | create_course/update_course now pass through show_ai_score | REQ: 20260824-playtest-score-visibility TECH: tech-design §3.4 |
/@changelog

@author chuckyang123
"""
import logging
from typing import Optional, Sequence
from datetime import datetime

from django.utils.timezone import get_default_timezone

from django.db.models import QuerySet, Prefetch
from django.db import IntegrityError, transaction

from pigeonhole.common.constants import (
    NAME,
    OWNER,
    DESCRIPTION,
    IS_PUBLISHED,
    SHOW_GROUP_MEMBERS_NAMES,
    ALLOW_STUDENTS_TO_CREATE_GROUPS,
    ALLOW_STUDENTS_TO_DELETE_GROUPS,
    ALLOW_STUDENTS_TO_JOIN_GROUPS,
    ALLOW_STUDENTS_TO_LEAVE_GROUPS,
    ALLOW_STUDENTS_TO_MODIFY_GROUP_NAME,
    ALLOW_STUDENTS_TO_ADD_OR_REMOVE_GROUP_MEMBERS,
    MILESTONE_ALIAS,
    SHOW_AI_SCORE,
    START_DATE_TIME,
    END_DATE_TIME,
    ROLE,
    USER,
    MEMBER_COUNT,
    MEMBERS,
    SUBMISSION_TYPE,
    FORM_FIELD_DATA,
    IS_DRAFT,
    CREATOR,
    EDITOR,
    FORM_RESPONSE_DATA,
    TEMPLATE,
    GROUP,
    MILESTONE,
    ID,
    COMMENTS,
    COMMENTER,
    FIELD_INDEX,
    CONTENT,
    IS_DELETED,
    VISIBILITY,
)
from pigeonhole.common.parsers import to_base_json, parse_datetime_to_ms_timestamp
from forms.models import Form
from users.models import User
from users.logic import user_to_json, get_users

from .models import (
    Comment,
    Course,
    CourseGroup,
    CourseGroupMember,
    CourseMembership,
    CourseMilestone,
    CourseMilestoneTemplate,
    CourseSettings,
    CourseSubmission,
    CourseSubmissionComment,
    CourseSubmissionViewableGroup,
    PatchCourseGroupAction,
    Role,
    SubmissionType,
    VisibilityStatus,
)

logger = logging.getLogger("main")


def get_courses(*args, **kwargs) -> QuerySet[Course]:
    return Course.objects.filter(*args, **kwargs)


def get_requested_course_submissions(
    course: Course,
    milestone_id: Optional[int],
    group_id: Optional[int],
    creator_id: Optional[int],
    editor_id: Optional[int],
    template_id: Optional[int],
) -> QuerySet[CourseSubmission]:
    submissions: QuerySet[
        CourseSubmission
    ] = course.coursesubmission_set.select_related(
        "milestone",
        "group",
        "template__form",
        "creator__user__profile_image",
        "editor__user__profile_image",
    )

    if milestone_id is not None:
        submissions = submissions.filter(milestone_id=milestone_id)

    if group_id is not None:
        submissions = submissions.filter(group_id=group_id)

    if creator_id is not None:
        submissions = submissions.filter(creator__user_id=creator_id)

    if editor_id is not None:
        submissions = submissions.filter(editor__user_id=editor_id)

    if template_id is not None:
        submissions = submissions.filter(template_id=template_id)

    return submissions


def get_course_submission_comments(
    submission: CourseSubmission,
) -> QuerySet[CourseSubmissionComment]:
    return submission.coursesubmissioncomment_set.select_related(
        "comment__commenter__profile_image", "member"
    )


def course_summary_to_json(course: Course, membership: CourseMembership) -> dict:
    data = to_base_json(course)

    data |= {
        NAME: course.name,
        OWNER: user_to_json(course.owner),
        DESCRIPTION: course.description,
        IS_PUBLISHED: course.is_published,
        ROLE: membership.role,
    }

    return data


def course_to_json(course: Course, membership: CourseMembership) -> dict:
    data = course_summary_to_json(course=course, membership=membership)

    course_settings: CourseSettings = course.coursesettings
    data |= {
        SHOW_GROUP_MEMBERS_NAMES: course_settings.show_group_members_names,
        ALLOW_STUDENTS_TO_CREATE_GROUPS: course_settings.allow_students_to_create_groups,
        ALLOW_STUDENTS_TO_DELETE_GROUPS: course_settings.allow_students_to_delete_groups,
        ALLOW_STUDENTS_TO_JOIN_GROUPS: course_settings.allow_students_to_join_groups,
        ALLOW_STUDENTS_TO_LEAVE_GROUPS: course_settings.allow_students_to_leave_groups,
        ALLOW_STUDENTS_TO_MODIFY_GROUP_NAME: course_settings.allow_students_to_modify_group_name,
        ALLOW_STUDENTS_TO_ADD_OR_REMOVE_GROUP_MEMBERS: course_settings.allow_students_to_add_or_remove_group_members,
        MILESTONE_ALIAS: course_settings.milestone_alias,
        SHOW_AI_SCORE: course_settings.show_ai_score,
    }

    return data


def course_milestone_to_json(milestone: CourseMilestone) -> dict:
    data = to_base_json(milestone)

    data |= {
        NAME: milestone.name,
        DESCRIPTION: milestone.description,
        START_DATE_TIME: parse_datetime_to_ms_timestamp(milestone.start_date_time),
        END_DATE_TIME: parse_datetime_to_ms_timestamp(milestone.end_date_time),
        IS_PUBLISHED: milestone.is_published,
    }

    return data


def course_membership_to_json(membership: CourseMembership) -> dict:
    data = to_base_json(membership)

    data |= {
        USER: user_to_json(membership.user),
        ROLE: membership.role,
    }

    return data


def course_group_to_json(group: CourseGroup) -> dict:
    data = to_base_json(group)

    data |= {NAME: group.name, MEMBER_COUNT: group.coursegroupmember_set.count()}

    return data


def course_group_with_members_to_json(group: CourseGroup) -> dict:
    data = course_group_to_json(group=group)

    data |= {
        MEMBERS: [
            user_to_json(group_member.member.user)
            for group_member in group.coursegroupmember_set.all()
        ],
    }

    return data


def course_milestone_template_to_json(template: CourseMilestoneTemplate) -> dict:
    data = to_base_json(template)

    data |= {
        NAME: template.form.name,
        DESCRIPTION: template.description,
        SUBMISSION_TYPE: template.submission_type,
        IS_PUBLISHED: template.is_published,
        FORM_FIELD_DATA: template.form.form_field_data,
    }

    return data


def course_submission_summary_to_json(submission: CourseSubmission) -> dict:
    data = to_base_json(submission)

    data |= {
        NAME: submission.name,
        DESCRIPTION: submission.description,
        IS_DRAFT: submission.is_draft,
        SUBMISSION_TYPE: submission.submission_type,
        CREATOR: user_to_json(submission.creator.user)
        if submission.creator is not None
        else None,
        EDITOR: user_to_json(submission.editor.user)
        if submission.editor is not None
        else None,
        MILESTONE: {ID: submission.milestone.id, NAME: submission.milestone.name}
        if submission.milestone is not None
        else None,
        GROUP: {ID: submission.group.id, NAME: submission.group.name}
        if submission.group is not None
        else None,
        VISIBILITY: VisibilityStatus.PUBLISHED 
        if submission.coursesubmissionviewablegroup_set.count() > 0
        else VisibilityStatus.PRIVATE,
    }

    return data


def comment_to_json(comment: Comment) -> dict:
    data = to_base_json(comment)

    data |= {
        COMMENTER: user_to_json(comment.commenter)
        if comment.commenter is not None
        else None,
        CONTENT: "" if comment.is_deleted else comment.content,
        IS_DELETED: comment.is_deleted,
    }

    return data


def course_submission_comment_to_json(
    submission_comment: CourseSubmissionComment,
) -> dict:
    data = comment_to_json(submission_comment.comment)

    data |= {
        FIELD_INDEX: submission_comment.field_index,
        ROLE: submission_comment.member.role
        if submission_comment.member is not None
        else None,
    }

    data[ID] = submission_comment.id

    return data


def course_submission_to_json(
    submission: CourseSubmission, with_comments: bool = False
) -> dict:
    data = course_submission_summary_to_json(submission)

    data |= {
        TEMPLATE: course_milestone_template_to_json(submission.template)
        if submission.template is not None
        else None,
        FORM_RESPONSE_DATA: submission.form_response_data,
        VISIBILITY: VisibilityStatus.PUBLISHED 
        if submission.coursesubmissionviewablegroup_set.count() > 0
        else VisibilityStatus.PRIVATE,
    }

    if with_comments:
        comments = get_course_submission_comments(submission)
        data |= {
            COMMENTS: [
                course_submission_comment_to_json(comment) for comment in comments
            ]
        }

    return data


@transaction.atomic
def create_course(
    owner: User,
    name: str,
    description: str,
    is_published: bool,
    show_group_members_names: bool,
    allow_students_to_create_groups: bool,
    allow_students_to_delete_groups: bool,
    allow_students_to_join_groups: bool,
    allow_students_to_leave_groups: bool,
    allow_students_to_modify_group_name: bool,
    allow_students_to_add_or_remove_group_members: bool,
    milestone_alias: str,
    show_ai_score: bool,
) -> tuple[Course, CourseMembership]:
    new_course = Course.objects.create(
        owner=owner,
        name=name,
        description=description,
        is_published=is_published,
    )

    ## create course settings
    new_course.coursesettings = CourseSettings.objects.create(
        course=new_course,
        show_group_members_names=show_group_members_names,
        allow_students_to_create_groups=allow_students_to_create_groups,
        allow_students_to_delete_groups=allow_students_to_delete_groups,
        allow_students_to_join_groups=allow_students_to_join_groups,
        allow_students_to_leave_groups=allow_students_to_leave_groups,
        allow_students_to_modify_group_name=allow_students_to_modify_group_name,
        allow_students_to_add_or_remove_group_members=allow_students_to_add_or_remove_group_members,
        milestone_alias=milestone_alias.lower(),
        show_ai_score=show_ai_score,
    )

    ## IMPORTANT!! make owner as course member
    new_member = CourseMembership.objects.create(
        user=owner, course=new_course, role=Role.CO_OWNER
    )

    return new_course, new_member


@transaction.atomic
def update_course(
    course: Course,
    owner_id: Optional[int],
    name: str,
    description: str,
    is_published: bool,
    show_group_members_names: bool,
    allow_students_to_create_groups: bool,
    allow_students_to_delete_groups: bool,
    allow_students_to_join_groups: bool,
    allow_students_to_leave_groups: bool,
    allow_students_to_modify_group_name: bool,
    allow_students_to_add_or_remove_group_members: bool,
    milestone_alias: str,
    show_ai_score: bool,
) -> Course:
    try:
        owner_membership = (
            None
            if owner_id is None or owner_id == course.owner.id
            else course.coursemembership_set.select_related("user__profile_image").get(
                user_id=owner_id
            )
        )
    except CourseMembership.DoesNotExist as e:
        logger.warning(e)
        raise ValueError("New owner is not in this course.")

    if owner_membership is not None:
        course.owner = owner_membership.user

        ## make new owner co-owner role
        if owner_membership.role != Role.CO_OWNER:
            owner_membership.role = Role.CO_OWNER
            owner_membership.save()

    course.name = name
    course.description = description
    course.is_published = is_published
    course.save()

    course_settings: CourseSettings = course.coursesettings
    course_settings.show_group_members_names = show_group_members_names
    course_settings.allow_students_to_create_groups = allow_students_to_create_groups
    course_settings.allow_students_to_delete_groups = allow_students_to_delete_groups
    course_settings.allow_students_to_join_groups = allow_students_to_join_groups
    course_settings.allow_students_to_leave_groups = allow_students_to_leave_groups
    course_settings.allow_students_to_modify_group_name = (
        allow_students_to_modify_group_name
    )
    course_settings.allow_students_to_add_or_remove_group_members = (
        allow_students_to_add_or_remove_group_members
    )
    course_settings.milestone_alias = milestone_alias.lower()
    course_settings.show_ai_score = show_ai_score
    course_settings.save()

    return course


@transaction.atomic
def create_course_milestone(
    course: Course,
    name: str,
    description: str,
    start_date_time: datetime,
    end_date_time: Optional[datetime],
    is_published: bool,
) -> CourseMilestone:
    try:
        new_milestone = CourseMilestone.objects.create(
            course=course,
            name=name,
            description=description,
            start_date_time=start_date_time,
            end_date_time=end_date_time,
            is_published=is_published,
        )
    except IntegrityError as e:
        logger.warning(e)
        raise ValueError(
            f"Another {course.coursesettings.milestone_alias or MILESTONE} with the same name already exists in this course."
        )

    return new_milestone


@transaction.atomic
def update_course_milestone(
    milestone: CourseMilestone,
    name: str,
    description: str,
    start_date_time: datetime,
    end_date_time: Optional[datetime],
    is_published: bool,
) -> CourseMilestone:
    milestone.name = name
    milestone.description = description
    milestone.start_date_time = start_date_time
    milestone.end_date_time = end_date_time
    milestone.is_published = is_published

    milestone.save()

    return milestone


def is_milestone_active(
    milestone: CourseMilestone, now: Optional[datetime] = None
) -> bool:
    if now is None:
        now = datetime.now(tz=get_default_timezone())

    return milestone.start_date_time <= now and (
        milestone.end_date_time is None or now <= milestone.end_date_time
    )


@transaction.atomic
def create_course_membership(
    user_id: int, course: Course, role: Role
) -> CourseMembership:
    try:
        user = get_users(id=user_id).select_related("profile_image").get()
    except User.DoesNotExist as e:
        logger.warning(e)
        raise ValueError("No user found.")

    try:
        new_membership = CourseMembership.objects.create(
            user=user, course=course, role=role
        )
    except IntegrityError as e:
        logger.warning(e)
        raise ValueError("User already exists in this course.")

    return new_membership


@transaction.atomic
def update_course_membership(
    membership: CourseMembership, role: Role
) -> CourseMembership:
    membership.role = role
    membership.save()

    return membership


@transaction.atomic
def create_course_group(course: Course, name: str) -> CourseGroup:
    try:
        new_group = CourseGroup.objects.create(course=course, name=name)
    except IntegrityError as e:
        logger.warning(e)
        raise ValueError(
            "Another group with the same name already exists in this course."
        )

    return new_group


def can_create_course_group(course: Course, membership: CourseMembership) -> bool:
    return (
        membership.role != Role.STUDENT
        or course.coursesettings.allow_students_to_create_groups
    )


def is_group_member(
    membership: CourseMembership, group: CourseGroup, force_query_db: bool = False
) -> bool:
    if force_query_db:
        return group.coursegroupmember_set.filter(member=membership).exists()

    return any(
        group_member.member == membership
        for group_member in group.coursegroupmember_set.all()
    )


def can_view_course_group_members(
    course: Course, membership: CourseMembership, group: CourseGroup
) -> bool:
    return (
        membership.role != Role.STUDENT
        or course.coursesettings.show_group_members_names
        or is_group_member(membership=membership, group=group)
    )


def can_update_course_group(
    course: Course,
    membership: CourseMembership,
    group: CourseGroup,
    action: PatchCourseGroupAction,
) -> bool:
    if membership.role != Role.STUDENT:
        return True

    course_settings: CourseSettings = course.coursesettings

    match action:
        case PatchCourseGroupAction.MODIFY:
            return (
                course_settings.allow_students_to_modify_group_name
                and is_group_member(membership=membership, group=group)
            )
        case PatchCourseGroupAction.JOIN:
            return course_settings.allow_students_to_join_groups
        case PatchCourseGroupAction.LEAVE:
            return course_settings.allow_students_to_leave_groups and is_group_member(
                membership=membership, group=group
            )
        case PatchCourseGroupAction.ADD | PatchCourseGroupAction.REMOVE:
            return (
                course_settings.allow_students_to_add_or_remove_group_members
                and is_group_member(membership=membership, group=group)
            )
        case _:
            return False


def can_delete_course_group(
    course: Course,
    membership: CourseMembership,
    group: CourseGroup,
) -> bool:
    return membership.role != Role.STUDENT or (
        course.coursesettings.allow_students_to_delete_groups
        and is_group_member(membership=membership, group=group)
    )


@transaction.atomic
def update_course_group(group: CourseGroup, name: str) -> CourseGroup:
    group.name = name
    group.save()

    return group


@transaction.atomic
def batch_update_course_group_members(
    course: Course, group: CourseGroup, user_ids: Sequence[int]
) -> CourseGroup:

    # delete members whose ids are not in list of ids
    group_members_to_delete = CourseGroupMember.objects.filter(group=group).exclude(
        member__user__id__in=user_ids
    )
    _, _ = group_members_to_delete.delete()

    # add members that are not in group
    for user_id in user_ids:
        try:
            membership = course.coursemembership_set.get(user_id=user_id)

            if CourseGroupMember.objects.filter(
                group=group, member_id=membership.id
            ).exists():
                continue

            CourseGroupMember.objects.create(member=membership, group=group)
        except CourseMembership.DoesNotExist as e:
            logger.warning(e)
            raise ValueError(
                "One or more of the members are not a part of this course."
            )
        except IntegrityError as e:
            logger.warning(e)
            raise ValueError("Unable to add a member to the group.")

    updated_group = CourseGroup.objects.prefetch_related(
        Prefetch(
            lookup="coursegroupmember_set",
            queryset=CourseGroupMember.objects.select_related(
                "member__user__profile_image"
            ),
        )
    ).get(id=group.id)

    return updated_group


@transaction.atomic
def update_course_group_members(
    course: Course,
    requester_membership: CourseMembership,
    group: CourseGroup,
    user_id: Optional[int],
    action: PatchCourseGroupAction,
) -> CourseGroup:
    match action:
        case PatchCourseGroupAction.ADD | PatchCourseGroupAction.REMOVE:
            try:
                membership = course.coursemembership_set.get(user_id=user_id)
            except CourseMembership.DoesNotExist as e:
                logger.warning(e)
                raise ValueError("No such user found in this course.")

        case PatchCourseGroupAction.JOIN | PatchCourseGroupAction.LEAVE:
            membership = requester_membership

        case _:  ## should never enter this case
            logger.warning(f"Invalid action: {action}")
            raise ValueError("Invalid action.")

    match action:
        case PatchCourseGroupAction.JOIN | PatchCourseGroupAction.ADD:
            try:
                CourseGroupMember.objects.create(member=membership, group=group)
            except IntegrityError as e:
                logger.warning(e)
                raise ValueError("User already exists in this group.")

        case PatchCourseGroupAction.LEAVE | PatchCourseGroupAction.REMOVE:
            num_deleted, _ = CourseGroupMember.objects.filter(
                member=membership, group=group
            ).delete()

            if num_deleted == 0:
                logger.warning(f"Action cannot be executed: {action}")
                raise ValueError("User does not exist in this group.")

        case _:  ## should never enter this case
            logger.warning(f"Invalid action: {action}")
            raise ValueError("Invalid action.")

    updated_group = CourseGroup.objects.prefetch_related(
        Prefetch(
            lookup="coursegroupmember_set",
            queryset=CourseGroupMember.objects.select_related(
                "member__user__profile_image"
            ),
        )
    ).get(id=group.id)

    return updated_group


@transaction.atomic
def create_course_milestone_template(
    course: Course,
    name: str,
    description: str,
    submission_type: SubmissionType,
    is_published: bool,
    form_field_data: Sequence[dict],
) -> CourseMilestoneTemplate:
    new_form = Form.objects.create(name=name, form_field_data=form_field_data)

    new_template = CourseMilestoneTemplate.objects.create(
        course=course,
        form=new_form,
        description=description,
        submission_type=submission_type,
        is_published=is_published,
    )

    return new_template


@transaction.atomic
def update_course_milestone_template(
    template: CourseMilestoneTemplate,
    name: str,
    description: str,
    submission_type: SubmissionType,
    is_published: bool,
    form_field_data: Sequence[dict],
) -> CourseMilestoneTemplate:
    template.form.name = name
    template.form.form_field_data = form_field_data

    template.form.save()

    template.description = description
    template.submission_type = submission_type
    template.is_published = is_published

    template.save()

    return template


def can_view_course_milestone_template(
    template: CourseMilestoneTemplate, requester_membership: CourseMembership
) -> bool:
    return template.is_published or requester_membership.role != Role.STUDENT


@transaction.atomic
def create_course_submission(
    course: Course,
    requester_membership: CourseMembership,
    milestone_id: int,
    group_id: Optional[int],
    template_id: int,
    name: str,
    description: str,
    is_draft: bool,
    submission_type: SubmissionType,
    form_response_data: Sequence[dict],
) -> CourseSubmission:
    try:
        milestone = course.coursemilestone_set.get(id=milestone_id)

    except CourseMilestone.DoesNotExist as e:
        logger.warning(e)
        raise ValueError(
            f"No such {course.coursesettings.milestone_alias or MILESTONE} found in this course."
        )

    try:
        template = course.coursemilestonetemplate_set.select_related("form").get(
            id=template_id
        )

    except CourseMilestoneTemplate.DoesNotExist as e:
        logger.warning(e)
        raise ValueError(f"No such template found in this course.")

    if not is_milestone_active(milestone=milestone):
        raise ValueError(
            f"{(course.coursesettings.milestone_alias or MILESTONE).capitalize()} is not open."
        )

    group = None
    if group_id is not None:
        try:
            group = course.coursegroup_set.get(id=group_id)

            if requester_membership.role == Role.STUDENT and not is_group_member(
                membership=requester_membership, group=group, force_query_db=True
            ):
                raise ValueError("User is not part of the group.")

        except CourseGroup.DoesNotExist as e:
            logger.warning(e)
            raise ValueError("No such group found in this course.")

    new_submission = CourseSubmission.objects.create(
        course=course,
        milestone=milestone,
        group=group,
        template=template,
        creator=requester_membership,
        editor=requester_membership,
        name=name,
        description=description,
        is_draft=is_draft,
        submission_type=submission_type,
        form_response_data=form_response_data,
    )

    return new_submission


@transaction.atomic
def update_course_submission(
    submission: CourseSubmission,
    course: Course,
    requester_membership: CourseMembership,
    group_id: Optional[int],
    name: str,
    description: str,
    is_draft: bool,
    submission_type: SubmissionType,
    form_response_data: Sequence[dict],
) -> CourseSubmission:
    if group_id != submission.group_id:
        group = None

        if group_id is not None:
            try:
                group = course.coursegroup_set.get(id=group_id)

                if requester_membership.role == Role.STUDENT and not is_group_member(
                    membership=requester_membership, group=group, force_query_db=True
                ):
                    raise ValueError("User is not part of the group.")

            except CourseGroup.DoesNotExist as e:
                logger.warning(e)
                raise ValueError("No such group found in this course.")

        submission.group = group

    submission.name = name
    submission.description = description
    submission.is_draft = is_draft
    submission.submission_type = submission_type
    submission.form_response_data = form_response_data
    submission.editor = requester_membership

    submission.save()

    return submission


def can_view_course_submission(
    requester_membership: CourseMembership, submission: CourseSubmission
) -> bool:
    return (
        requester_membership.role != Role.STUDENT
        or submission.creator == requester_membership
        or (
            submission.group is not None
            and is_group_member(
                membership=requester_membership,
                group=submission.group,
                force_query_db=True,
            )
        )
        or any(
            requester_membership == viewable_member.member
            for viewable_member in submission.coursesubmissionviewablemember_set.select_related(
                "member"
            )
        )
        or any(
            is_group_member(
                membership=requester_membership,
                group=viewable_group.group,
                force_query_db=True,
            )
            for viewable_group in submission.coursesubmissionviewablegroup_set.select_related(
                "group"
            )
        )
    )


def can_update_course_submission(
    requester_membership: CourseMembership, submission: CourseSubmission
) -> bool:
    if not can_view_course_submission(
        requester_membership=requester_membership, submission=submission
    ):
        return False

    if submission.milestone is not None:
        return is_milestone_active(milestone=submission.milestone)

    return True


can_delete_course_submission = can_update_course_submission


def can_update_course_submission_comment(
    requester_membership: CourseMembership,
    submission_comment: CourseSubmissionComment,
) -> bool:
    return requester_membership == submission_comment.member


can_delete_course_submission_comment = can_update_course_submission_comment


@transaction.atomic
def create_course_submission_comment(
    submission: CourseSubmission,
    commenter: User,
    content: str,
    field_index: int,
    member: CourseMembership,
) -> CourseSubmissionComment:

    new_comment = Comment.objects.create(content=content, commenter=commenter)

    new_submission_comment = CourseSubmissionComment.objects.create(
        submission=submission,
        comment=new_comment,
        field_index=field_index,
        member=member,
    )

    return new_submission_comment


@transaction.atomic
def update_course_submission_comment(
    submission_comment: CourseSubmissionComment, content: str
) -> CourseSubmissionComment:

    comment = submission_comment.comment
    comment.content = content

    comment.save()

    return submission_comment


@transaction.atomic
def delete_course_submission_comment(
    submission_comment: CourseSubmissionComment,
) -> CourseSubmissionComment:

    comment = submission_comment.comment
    comment.is_deleted = True

    comment.save()

    return submission_comment


@transaction.atomic
def batch_update_course_submission_viewable_groups(
    course: Course, submission: CourseSubmission, group_ids: Sequence[int]
) -> CourseSubmission:

    # delete viewable groups whose ids are not in list of ids
    viewable_groups_to_delete = CourseSubmissionViewableGroup.objects.filter(submission=submission).exclude(
        group__id__in=group_ids
    )
    _, _ = viewable_groups_to_delete.delete()

    # add groups that have no viewable groups yet
    for group_id in group_ids:
        try:
            group = course.coursegroup_set.get(id=group_id)

            if CourseSubmissionViewableGroup.objects.filter(
                submission=submission, group__id=group_id
            ).exists():
                continue

            CourseSubmissionViewableGroup.objects.create(submission=submission, group=group)
        except CourseGroup.DoesNotExist as e:
            logger.warning(e)
            raise ValueError(
                "One or more of the groups are not a part of this course."
            )
        except IntegrityError as e:
            logger.warning(e)
            raise ValueError("Unable to publish the submission to a group.")

    updated_viewable_groups = submission.coursesubmissionviewablegroup_set \
        .prefetch_related('group').all()

    return updated_viewable_groups
