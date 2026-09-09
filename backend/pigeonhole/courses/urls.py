"""
@changelog
| Version | Description                                            | Reference                                     |
| v1.0.0 | Initial implementation (indexed baseline)              |                                               |
| v1.1.0 | Registered memberships/import bulk import endpoint     | REQ: 20260908-课程名单分组导入 TECH: 04_design_tech-design.md §3.3 |
/@changelog

@author chuckyang123
"""
from django.urls import path

from .views import (
    CourseSubmissionViewableGroupsView,
    MyCoursesView,
    SingleCourseView,
    CourseMilestonesView,
    SingleCourseMilestoneView,
    CourseMembershipsView,
    SingleCourseMembershipView,
    CourseGroupsView,
    SingleCourseGroupView,
    CourseMilestoneTemplatesView,
    SingleCourseMilestoneTemplateView,
    CourseSubmissionsView,
    SingleCourseSubmissionView,
    CourseSubmissionFieldCommentsView,
    CourseSubmissionSingleFieldCommentsView,
    SingleCourseSubmissionCommentView,
    CourseMembershipsWithNewUserCreationView,
    CourseMembershipsImportView
)

urlpatterns = [
    path("", MyCoursesView.as_view(), name="my_courses"),
    path("<int:course_id>/", SingleCourseView.as_view(), name="single_course"),
    path(
        "<int:course_id>/milestones/",
        CourseMilestonesView.as_view(),
        name="course_milestones",
    ),
    path(
        "<int:course_id>/milestones/<int:milestone_id>/",
        SingleCourseMilestoneView.as_view(),
        name="single_course_milestone",
    ),
    path(
        "<int:course_id>/templates/",
        CourseMilestoneTemplatesView.as_view(),
        name="course_milestone_templates",
    ),
    path(
        "<int:course_id>/templates/<int:template_id>/",
        SingleCourseMilestoneTemplateView.as_view(),
        name="single_course_milestone_template",
    ),
    path(
        "<int:course_id>/submissions/",
        CourseSubmissionsView.as_view(),
        name="course_submissions",
    ),
    path(
        "<int:course_id>/submissions/<int:submission_id>/",
        SingleCourseSubmissionView.as_view(),
        name="single_course_submission",
    ),
    path(
        "<int:course_id>/memberships/",
        CourseMembershipsView.as_view(),
        name="course_memberships",
    ),
    path(
        "<int:course_id>/memberships/new",
        CourseMembershipsWithNewUserCreationView.as_view(),
        name="course_memberships_with_new_user_creation",
    ),
    path(
        "<int:course_id>/memberships/import",
        CourseMembershipsImportView.as_view(),
        name="course_memberships_import",
    ),
    path(
        "<int:course_id>/memberships/<int:member_id>/",
        SingleCourseMembershipView.as_view(),
        name="single_course_membership",
    ),
    path(
        "<int:course_id>/groups/",
        CourseGroupsView.as_view(),
        name="course_groups",
    ),
    path(
        "<int:course_id>/groups/<int:group_id>/",
        SingleCourseGroupView.as_view(),
        name="single_course_group",
    ),
    path(
        "<int:course_id>/submissions/<int:submission_id>/fields/comments/",
        CourseSubmissionFieldCommentsView.as_view(),
        name="course_submission_field_comments",
    ),
    path(
        "<int:course_id>/submissions/<int:submission_id>/fields/<int:field_index>/comments/",
        CourseSubmissionSingleFieldCommentsView.as_view(),
        name="course_submission_single_field_comments",
    ),
    path(
        "<int:course_id>/submissions/<int:submission_id>/comments/<int:comment_id>",
        SingleCourseSubmissionCommentView.as_view(),
        name="single_course_submission_comment",
    ),
    path(
        "<int:course_id>/submissions/<int:submission_id>/viewable-groups",
        CourseSubmissionViewableGroupsView.as_view(),
        name="course_submission_viewable_groups",
    ),
]
