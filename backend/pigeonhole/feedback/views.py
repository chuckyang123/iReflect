"""
@changelog
| Version | Description                                      | Reference                                   |
| v1.0.0  | Initial implementation: feedback generation and initial response collection views |                                             |
| v1.1.0  | Reworked FeedbackView: persist submission_id/question | REQ: 20260818-feedback-modification-tracking |
|         | Added FeedbackRecordView: Playtest reporting + querying | TECH: 04_design_tech-design.md §3.3          |
| v1.2.0  | FeedbackRecordView.post strips score_json based on course show_ai_score | REQ: 20260824-playtest-score-visibility TECH: tech-design §3.6 |
| v1.3.0  | FeedbackRecordView.get supports submission_id filter | REQ: 20260818-feedback-modification-tracking |
|         | (feedback version history per submission)      | TECH: tech-design §3.3                      |
| v1.4.0  | Returns 503 without OPENAI_API_KEY and not in DEBUG, avoiding mock feedback in production | PRD: production fails loudly |
| v1.5.0  | FeedbackView.post strips numeric scores for STANDARD students when the course disables show_ai_score (record keeps full text); initial-response tolerates absent genre/mechanic | REQ: 20260824-playtest-score-visibility TECH: tech-design §3.6 |
| v1.6.0  | FeedbackRecordView.get authorizes STANDARD users by their course role (INSTRUCTOR/CO_OWNER) instead of the global account_type, fixing 403 for invited instructors whose account_type is still STANDARD | BUG: feedback-history-empty |
/@changelog

@author chuckyang123
"""
from rest_framework import status
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response
from rest_framework.views import APIView

from pigeonhole.common.exceptions import BadRequest
from courses.models import CourseMembership, Role
from users.middlewares import check_account_access
from users.models import AccountType, User

from .logic import (
    FeedbackNotConfiguredError,
    askChatGPT,
    askChatGPTOriginal,
    ai_feedback_record_to_json,
    createFeedbackInitialResponseIfNotExists,
    create_feedback_version_and_record,
    feedback_answer_version_to_json,
    feedback_initial_response_to_json,
    resolve_show_ai_score,
    strip_scores_from_feedback_text,
)
from .models import AIFeedbackRecord, FeedbackAnswerVersion
from .serializers import (
    FeedbackRecordQuerySerializer,
    PostFeedbackInitialResponseSerializer,
    PostFeedbackRecordSerializer,
    PostFeedbackSerializer,
)


# Create your views here.
class FeedbackView(APIView):
    @check_account_access(AccountType.STANDARD, AccountType.EDUCATOR, AccountType.ADMIN)
    def post(self, request, requester: User):
        serializer = PostFeedbackSerializer(data=request.data)

        serializer.is_valid(raise_exception=True)
        validated_data = serializer.validated_data

        # No annotated content from ChatGPT, only feedback
        annotated_content = ''

        try:
            if requester.id % 2 == 0:
                strategy = AIFeedbackRecord.STRATEGY_BASIC
                feedback, score_json, token_usage_json, latency_ms = askChatGPTOriginal(
                    validated_data["content"]
                )
            else:
                strategy = AIFeedbackRecord.STRATEGY_ADVANCED
                feedback, score_json, token_usage_json, latency_ms = askChatGPT(
                    validated_data["content"]
                )
        except FeedbackNotConfiguredError as e:
            # Production must fail loudly instead of serving simulated scores.
            return Response(
                data={"detail": str(e)},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        # Persist transactionally: answer version snapshot + AI feedback record (only when submission_id is provided)
        if validated_data.get("submission_id") and validated_data.get("question"):
            try:
                record = create_feedback_version_and_record(
                    submission_id=validated_data["submission_id"],
                    requester=requester,
                    question=validated_data["question"],
                    answer_content=validated_data["content"],
                    feedback_type=AIFeedbackRecord.FEEDBACK_TYPE_REFLECTION,
                    strategy=strategy,
                    feedback_content=feedback,
                    score_json=score_json,
                    token_usage_json=token_usage_json,
                    latency_ms=latency_ms,
                )
            except ValueError as e:
                raise BadRequest(detail=e)
            record_id = record.id
        else:
            record_id = None

        # PRD 20260824-playtest-score-visibility: when the course hides AI scores,
        # STANDARD students receive the qualitative feedback with numeric scores
        # stripped. The record above keeps the full text for educator review.
        display_feedback = feedback
        if (
            requester.account_type == AccountType.STANDARD
            and validated_data.get("submission_id")
        ):
            show_ai_score = resolve_show_ai_score(validated_data["submission_id"])
            if show_ai_score is False:
                display_feedback = strip_scores_from_feedback_text(feedback)

        data = {
            "annotated_content": annotated_content,
            "feedback": display_feedback,
            "record_id": record_id,
        }

        return Response(data=data, status=status.HTTP_200_OK)


class FeedbackInitialResponseView(APIView):
    @check_account_access(AccountType.STANDARD, AccountType.EDUCATOR, AccountType.ADMIN)
    def post(
        self,
        request,
        requester: User,
    ):
        serializer = PostFeedbackInitialResponseSerializer(data=request.data)

        serializer.is_valid(raise_exception=True)
        validated_data = serializer.validated_data

        try:
            new_initial_response, created = createFeedbackInitialResponseIfNotExists(
                submission_id=validated_data["submission_id"],
                requester=requester,
                question=validated_data["question"],
                initial_response=validated_data["initial_response"],
                genre=validated_data.get("genre"),
                mechanic=validated_data.get("mechanic"),
            )
        except ValueError as e:
            raise BadRequest(detail=e)

        data = {"created": created}

        if (created):
            json_data = feedback_initial_response_to_json(new_initial_response)
            data["new_initial_response"] = json_data

        return Response(data=data, status=status.HTTP_200_OK)


class FeedbackRecordView(APIView):
    """AI feedback records: POST for frontend reporting (Playtest path), GET for educator/researcher queries."""

    @check_account_access(AccountType.STANDARD, AccountType.EDUCATOR, AccountType.ADMIN)
    def post(self, request, requester: User):
        serializer = PostFeedbackRecordSerializer(data=request.data)

        serializer.is_valid(raise_exception=True)
        validated_data = serializer.validated_data

        try:
            record = create_feedback_version_and_record(
                submission_id=validated_data["submission_id"],
                requester=requester,
                question=validated_data["question"],
                answer_content=validated_data["initial_response"],
                feedback_type=AIFeedbackRecord.FEEDBACK_TYPE_PLAYTEST,
                strategy=AIFeedbackRecord.STRATEGY_PLAYTEST,
                feedback_content=validated_data["feedback_content"],
                idempotency_key=validated_data.get("idempotency_key"),
                genre=validated_data.get("genre"),
                mechanic=validated_data.get("mechanic"),
            )
        except ValueError as e:
            raise BadRequest(detail=e)

        # PRD 20260824-playtest-score-visibility: student-facing response hides scores
        # unless the course enables show_ai_score; educators always keep them.
        include_score = True
        if requester.account_type == AccountType.STANDARD:
            course_settings = getattr(record.version.course, "coursesettings", None)
            include_score = bool(
                course_settings is not None and course_settings.show_ai_score
            )

        data = {
            "record": ai_feedback_record_to_json(record, include_score=include_score),
            "version": feedback_answer_version_to_json(record.version),
        }

        return Response(data=data, status=status.HTTP_200_OK)

    @check_account_access(AccountType.STANDARD, AccountType.EDUCATOR, AccountType.ADMIN)
    def get(self, request, requester: User):
        serializer = FeedbackRecordQuerySerializer(data=request.query_params)

        serializer.is_valid(raise_exception=True)
        params = serializer.validated_data

        versions = FeedbackAnswerVersion.objects.select_related(
            "course", "milestone", "template", "submission", "creator__user"
        ).prefetch_related("feedback_records").order_by(
            "creator", "question", "version_number"
        )

        if params.get("course_id"):
            versions = versions.filter(course_id=params["course_id"])
        if params.get("user_id"):
            versions = versions.filter(creator__user_id=params["user_id"])
        if params.get("milestone_id"):
            versions = versions.filter(milestone_id=params["milestone_id"])
        if params.get("submission_id"):
            versions = versions.filter(submission_id=params["submission_id"])
        if params.get("question"):
            versions = versions.filter(question=params["question"])

        # v1.6.0: STANDARD accounts are authorized by their role *inside the
        # course* (INSTRUCTOR/CO_OWNER), matching the frontend gate
        # (`canAccessFullDetails` in use-get-course-permissions.ts). The global
        # account_type is the wrong axis here: AccountType.EDUCATOR only means
        # "may create new courses" (users/models.py), so an instructor invited
        # into someone else's course keeps account_type=STANDARD and used to be
        # rejected with 403 while the frontend happily rendered the history
        # section. EDUCATOR/ADMIN keep unrestricted read access for research.
        if requester.account_type == AccountType.STANDARD:
            administered_course_ids = list(
                CourseMembership.objects.filter(
                    user=requester, role__in=[Role.INSTRUCTOR, Role.CO_OWNER]
                ).values_list("course_id", flat=True)
            )

            if not administered_course_ids:
                raise PermissionDenied()

            versions = versions.filter(course_id__in=administered_course_ids)

        data = [
            {
                **feedback_answer_version_to_json(version),
                "feedback_records": [
                    ai_feedback_record_to_json(record)
                    for record in version.feedback_records.all()
                ],
            }
            for version in versions
        ]

        return Response(data=data, status=status.HTTP_200_OK)
