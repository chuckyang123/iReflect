import { useRef, ElementRef, useEffect } from "react";
import {
  Button,
  createStyles,
  Group,
  LoadingOverlay,
  Paper,
  Stack,
  Text,
} from "@mantine/core";
import { useLocation, useNavigate } from "react-router-dom";
import path from "path";
import { useModals } from "@mantine/modals";
import { FaTrashAlt } from "react-icons/fa";
import { skipToken } from "@reduxjs/toolkit/query/react";
import useGetCourseId from "../../custom-hooks/use-get-course-id";
import useGetFormContainerStyle from "../../custom-hooks/use-get-form-container-style";
import useGetMilestoneId from "../../custom-hooks/use-get-milestone-id";
import useGetSubmissionId from "../../custom-hooks/use-get-submission-id";
import { useGetSingleMilestoneQueryState } from "../../redux/services/milestones-api";
import {
  useDeleteSubmissionMutation,
  useGetSingleSubmissionQuery,
  useUpdateSubmissionMutation,
} from "../../redux/services/submissions-api";
import { SubmissionPutData } from "../../types/submissions";
import { useResolveError } from "../../utils/error-utils";
import toastUtils from "../../utils/toast-utils";
import SubmissionForm, { SubmissionFormData } from "../submission-form";
import PlaceholderWrapper from "../placeholder-wrapper";
import { DATE_TIME_MONTH_NAME_FORMAT, UNKNOWN_USER } from "../../constants";
import { displayDateTime } from "../../utils/transform-utils";
import useGetCourseMilestoneSubmissionPermissions from "../../custom-hooks/use-get-course-milestone-submission-permissions";
import useGetCoursePermissions from "../../custom-hooks/use-get-course-permissions";
import ConditionalRenderer from "../conditional-renderer";
import { SubmissionType } from "../../types/templates";
import CourseSubmissionPublishSection from "../course-submission-publish-section";
import CourseSubmissionFeedbackHistorySection from "../course-submission-feedback-history-section";

const useStyles = createStyles({
  formContainer: {
    position: "relative",
  },
});

function CourseMilestoneSubmissionsViewPage() {
  const courseId = useGetCourseId();
  const milestoneId = useGetMilestoneId();
  const submissionId = useGetSubmissionId();
  const formContainerClassName = useGetFormContainerStyle();
  const { classes, cx } = useStyles();
  const { milestone } = useGetSingleMilestoneQueryState(
    courseId === undefined || milestoneId === undefined
      ? skipToken
      : { courseId, milestoneId },
    { selectFromResult: ({ data: milestone }) => ({ milestone }) },
  );
  const { submission, isFetching, isLoading, error } =
    useGetSingleSubmissionQuery(
      courseId === undefined || submissionId === undefined
        ? skipToken
        : { courseId, submissionId },
      {
        selectFromResult: ({
          data: submission,
          isFetching,
          isLoading,
          error,
        }) => ({
          submission,
          isFetching,
          isLoading,
          error,
        }),
        // get the most updated submission data before editing
        refetchOnMountOrArgChange: true,
        // do not want refetch while using is editing the form
        refetchOnReconnect: false,
      },
    );
  useResolveError({ error, name: "course-milestone-submissions-view-page" });
  const formRef = useRef<ElementRef<typeof SubmissionForm>>(null);
  const [updateSubmission, { isUpdating }] = useUpdateSubmissionMutation({
    selectFromResult: ({ isLoading: isUpdating }) => ({ isUpdating }),
  });
  const [deleteSubmission, { isDeleting }] = useDeleteSubmissionMutation({
    selectFromResult: ({ isLoading: isDeleting }) => ({ isDeleting }),
  });
  const { resolveError } = useResolveError({
    name: "course-milestone-submissions-view-page",
  });
  const navigate = useNavigate();
  const { pathname } = useLocation();
  const modals = useModals();
  const { canAccessFullDetails } = useGetCoursePermissions();
  const { canModify, canDelete } = useGetCourseMilestoneSubmissionPermissions();

  const onUpdateSubmission = async (formData: SubmissionFormData) => {
    if (
      isUpdating ||
      isDeleting ||
      courseId === undefined ||
      submissionId === undefined ||
      submission === undefined
    ) {
      return;
    }

    const { name, description } = submission;
    const { isDraft, submissionType, formResponseData, groupId } = formData;

    const submissionPutData: SubmissionPutData = {
      name,
      description,
      isDraft,
      submissionType,
      formResponseData,
      groupId,
    };

    await updateSubmission({
      ...submissionPutData,
      courseId,
      submissionId,
    }).unwrap();

    toastUtils.success({
      message: "This submission has been updated successfully.",
    });
  };

  const onDeleteSubmission = async () => {
    if (
      isUpdating ||
      isDeleting ||
      courseId === undefined ||
      submissionId === undefined
    ) {
      return;
    }

    try {
      await deleteSubmission({ courseId, submissionId }).unwrap();

      toastUtils.success({
        message: "The submission has been deleted successfully.",
      });

      navigate(path.resolve(pathname, "../"));
    } catch (error) {
      resolveError(error);
    }
  };

  const openDeleteModal = () =>
    modals.openConfirmModal({
      title: "Delete this submission",
      closeButtonLabel: "Cancel submission deletion",
      centered: true,
      children: (
        <Text size="sm">
          Are you sure you want to delete this submission (
          <strong>{submission?.name}</strong>)?
          <br />
          <strong>This action is destructive and irreversible.</strong>
        </Text>
      ),
      labels: { confirm: "Delete submission", cancel: "No don't delete" },
      confirmProps: { color: "red" },
      onConfirm: onDeleteSubmission,
    });

  useEffect(() => {
    if (submission) {
      formRef.current?.reset(submission);
    }
  }, [submission]);

  if (isLoading || !submission) {
    return (
      <PlaceholderWrapper
        py={150}
        isLoading={isLoading}
        loadingMessage="Loading submission..."
        showDefaultMessage={!submission}
        defaultMessage="No submission found."
      />
    );
  }

  const { creator, createdAt, editor, updatedAt } = submission;

  return (
    <Stack>
      <Group position="apart">
        <Group>
          <Group spacing={6}>
            <Text size="sm">Created by:</Text>
            <Paper withBorder p={6}>
              <Text size="sm">
                {`${creator?.name ?? UNKNOWN_USER} @ ${displayDateTime(
                  createdAt,
                  DATE_TIME_MONTH_NAME_FORMAT,
                )}`}
              </Text>
            </Paper>
          </Group>

          <Group spacing={6}>
            <Text size="sm">Last updated by:</Text>
            <Paper withBorder p={6}>
              <Text size="sm">
                {`${editor?.name ?? UNKNOWN_USER} @ ${displayDateTime(
                  updatedAt,
                  DATE_TIME_MONTH_NAME_FORMAT,
                )}`}
              </Text>
            </Paper>
          </Group>

          {milestone && milestone.endDateTime !== null && (
            <Group spacing={6}>
              <Text size="sm">Finalize by:</Text>
              <Paper withBorder p={6}>
                <Text size="sm">
                  {displayDateTime(
                    milestone.endDateTime,
                    DATE_TIME_MONTH_NAME_FORMAT,
                  )}
                </Text>
              </Paper>
            </Group>
          )}
        </Group>
      </Group>

      <ConditionalRenderer
        allow={
          canAccessFullDetails &&
          submission.submissionType === SubmissionType.Group
        }
      >
        <CourseSubmissionPublishSection
          courseId={courseId}
          submissionId={submissionId}
        />
      </ConditionalRenderer>

      <Group>
        <Button
          color="red"
          leftIcon={<FaTrashAlt size={12} />}
          loading={isDeleting}
          disabled={!canDelete || isUpdating}
          onClick={openDeleteModal}
        >
          Delete submission
        </Button>
      </Group>

      <Paper
        withBorder
        shadow="sm"
        radius="md"
        p="md"
        className={cx(classes.formContainer, formContainerClassName)}
      >
        <LoadingOverlay visible={isFetching} />
        <SubmissionForm
          ref={formRef}
          defaultValues={submission}
          readOnly={!canModify}
          onSubmit={onUpdateSubmission}
          withComments
          submitButtonProps={{ disabled: isDeleting }}
        />
      </Paper>

      <ConditionalRenderer allow={canAccessFullDetails}>
        <CourseSubmissionFeedbackHistorySection
          courseId={courseId}
          submissionId={submissionId}
        />
      </ConditionalRenderer>
    </Stack>
  );
}

export default CourseMilestoneSubmissionsViewPage;
