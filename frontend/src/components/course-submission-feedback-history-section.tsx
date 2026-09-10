import {
  Badge,
  Divider,
  Grid,
  Group,
  LoadingOverlay,
  Paper,
  Stack,
  Text,
  Title,
} from "@mantine/core";
import Markdown, { Components } from "react-markdown";
import { TbMessageChatbot, TbUserEdit } from "react-icons/tb";
import { skipToken } from "@reduxjs/toolkit/query/react";
/**
 * @changelog
 * | Version | Description                                          | Reference |
 * | v1.0.0 | Initial implementation: two-column feedback history view (student input / AI feedback) | REQ: 20260818-feedback-modification-tracking TECH: tech-design §3.3 |
 * /@changelog
 *
 * @author chuckyang123
 */
import { useGetFeedbackAnswerVersionsQuery } from "../redux/services/feedback-api";
import { FeedbackVersionHistoryData } from "../types/feedback";
import { useResolveError } from "../utils/error-utils";
import {
  ANSWER_CONTENT,
  DATE_TIME_MONTH_NAME_FORMAT,
  UNKNOWN_USER,
  VERSION_NUMBER,
} from "../constants";
import { displayDateTime } from "../utils/transform-utils";
import useGetCourseId from "../custom-hooks/use-get-course-id";
import { useGetSingleCourseQuery } from "../redux/services/courses-api";
import useGetCurrentUserAccountType from "../custom-hooks/use-get-current-user-account-type";
import { AccountType } from "../types/users";
import { stripScoresFromMarkdown } from "./form-field-playtest-feedback-renderer";

type Props = {
  courseId: string | number | undefined;
  submissionId: string | number | undefined;
};

const markdownComponents: Partial<Components> = {
  h1: ({ children }) => <Title order={2}>{children}</Title>,
  h2: ({ children }) => <Title order={3}>{children}</Title>,
  h3: ({ children }) => <Title order={4}>{children}</Title>,
  h4: ({ children }) => <Title order={5}>{children}</Title>,
  p: ({ children }) => <Text size="sm">{children}</Text>,
  li: ({ children }) => (
    <Text size="sm" component="li" mb="xs">
      {children}
    </Text>
  ),
  strong: ({ children }) => <Text weight={700}>{children}</Text>,
};

function CourseSubmissionFeedbackHistorySection({
  courseId,
  submissionId,
}: Props) {
  const {
    data: versions,
    isLoading,
    error,
  } = useGetFeedbackAnswerVersionsQuery(
    submissionId === undefined ? skipToken : { submission_id: submissionId },
    { refetchOnMountOrArgChange: true },
  );
  useResolveError({
    error,
    name: "course-submission-feedback-history-section",
  });

  // Show the raw feedback to educators/admins; strip numeric scores for
  // students unless the course explicitly enables showAiScore (REQ 20260824).
  const currentCourseId = useGetCourseId();
  const accountType = useGetCurrentUserAccountType();
  const { data: course } = useGetSingleCourseQuery(currentCourseId ?? "", {
    skip: !currentCourseId,
  });
  const shouldHideScores =
    accountType === AccountType.Standard && course?.showAiScore === false;

  if (isLoading || !versions) {
    return (
      <Paper withBorder shadow="sm" radius="md" p="md">
        <Title order={5} mb="sm">
          Feedback History
        </Title>
        <LoadingOverlay visible={isLoading} />
        {!versions && !isLoading && (
          <Text size="sm" color="dimmed">
            No feedback history available.
          </Text>
        )}
      </Paper>
    );
  }

  if (versions.length === 0) {
    return (
      <Paper withBorder shadow="sm" radius="md" p="md">
        <Title order={5} mb="sm">
          Feedback History
        </Title>
        <Text size="sm" color="dimmed">
          No feedback has been generated for this submission yet.
        </Text>
      </Paper>
    );
  }

  // Group versions by question, ordered by version number (timeline).
  const groups: Record<string, FeedbackVersionHistoryData[]> = [...versions]
    .sort((a, b) => (a[VERSION_NUMBER] ?? 0) - (b[VERSION_NUMBER] ?? 0))
    .reduce<Record<string, FeedbackVersionHistoryData[]>>((acc, version) => {
      const key = version.question;
      (acc[key] = acc[key] ?? []).push(version);
      return acc;
    }, {});

  return (
    <Paper withBorder shadow="sm" radius="md" p="md">
      <Stack spacing="md">
        <Group position="apart">
          <Title order={5}>Feedback History</Title>
          <Text size="xs" color="dimmed">
            Every time feedback is generated, the student&apos;s answer and the
            AI feedback are snapshotted as a new version.
          </Text>
        </Group>

        {Object.entries(groups).map(([question, questionVersions]) => (
          <Stack key={question} spacing="xs">
            <Text size="sm" weight={600}>
              {question}
            </Text>
            <Divider />

            {questionVersions.map((version, index) => {
              const feedbackContent =
                version.feedbackRecords?.[0]?.feedbackContent ?? null;
              const creatorName = version.creator?.name ?? UNKNOWN_USER;
              const createdAt = displayDateTime(
                version.createdAt,
                DATE_TIME_MONTH_NAME_FORMAT,
              );
              const isLatest = index === questionVersions.length - 1;

              return (
                <Paper
                  key={version.id}
                  withBorder
                  shadow="xs"
                  radius="md"
                  p="sm"
                  style={{ position: "relative" }}
                >
                  <Group position="apart" mb="xs">
                    <Group spacing={8}>
                      <Badge color={isLatest ? "blue" : "gray"}>
                        Version {version[VERSION_NUMBER]}
                      </Badge>
                      {isLatest && (
                        <Badge color="green" variant="light">
                          Latest
                        </Badge>
                      )}
                      <Text size="xs" color="dimmed">
                        {creatorName} @ {createdAt}
                      </Text>
                    </Group>
                  </Group>

                  <Grid gutter="md">
                    <Grid.Col span={12} md={6}>
                      <Paper
                        style={{ backgroundColor: "#f1f3f5" }}
                        radius="md"
                        p="sm"
                      >
                        <Group spacing={6} mb="xs">
                          <TbUserEdit size={14} />
                          <Text size="xs" weight={600} color="dimmed">
                            Student&apos;s Input
                          </Text>
                        </Group>
                        <Text
                          size="sm"
                          style={{
                            whiteSpace: "pre-wrap",
                            wordBreak: "break-word",
                          }}
                        >
                          {version[ANSWER_CONTENT]}
                        </Text>
                      </Paper>
                    </Grid.Col>

                    <Grid.Col span={12} md={6}>
                      <Paper
                        style={{ backgroundColor: "#e7f5ff" }}
                        radius="md"
                        p="sm"
                      >
                        <Group spacing={6} mb="xs">
                          <TbMessageChatbot size={14} />
                          <Text size="xs" weight={600} color="dimmed">
                            AI Feedback
                          </Text>
                        </Group>
                        {feedbackContent ? (
                          <Markdown components={markdownComponents}>
                            {shouldHideScores
                              ? stripScoresFromMarkdown(feedbackContent)
                              : feedbackContent}
                          </Markdown>
                        ) : (
                          <Text size="sm" color="dimmed">
                            No feedback recorded for this version.
                          </Text>
                        )}
                      </Paper>
                    </Grid.Col>
                  </Grid>
                </Paper>
              );
            })}
          </Stack>
        ))}
      </Stack>
    </Paper>
  );
}

export default CourseSubmissionFeedbackHistorySection;
