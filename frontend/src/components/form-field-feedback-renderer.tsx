/**
 * @changelog
 * | Version | Description                                            | Reference                                     |
 * | v1.0.0 | Initial implementation (indexed baseline)              |                                               |
 * | v1.1.0 | Student-side score hiding for reflection feedback: hide numeric scores when course disables showAiScore (server also strips) | REQ: 20260824-playtest-score-visibility TECH: tech-design §3.6 |
 * | v1.1.1 | Strip also matches the "Additional Stage. Readability and Accuracy: x / 2" heading (was leaking the score) | REQ: 20260824-playtest-score-visibility |
 * /@changelog
 *
 * @author chuckyang123
 */
import { Button, Text, Stack, Paper, Blockquote, Title } from "@mantine/core";
import { useFormContext } from "react-hook-form";
import { FaRegSmile } from "react-icons/fa";
import { TbMessageChatbot } from "react-icons/tb";
import { useContext } from "react";
import Markdown, { Components } from "react-markdown";
import {
  useCreateInitialResponseIfNotExistsMutation,
  useLazyGetFeedbackQuery,
} from "../redux/services/feedback-api";
import { useResolveError } from "../utils/error-utils";
import { FeedbackContext } from "../contexts/feedback-data-collection-provider";
import { useGetSingleCourseQuery } from "../redux/services/courses-api";
import useGetCourseId from "../custom-hooks/use-get-course-id";
import useGetCurrentUserAccountType from "../custom-hooks/use-get-current-user-account-type";
import { AccountType } from "../types/users";

/**
 * Drop the numeric score markers from educator-grade reflection feedback
 * markdown (Advanced ChatGPT flow):
 *   **Stage 1. Returning to Experience: 1 / 2**   ->   **Stage 1. Returning to Experience**
 *   **Total Score: 10 / 12**                       ->   (line removed)
 * Qualitative "what was done well / improvement / summary" content is kept.
 */
function stripScoresFromFeedbackMarkdown(markdown: string): string {
  return markdown
    .split("\n")
    .map((line) => {
      const trimmed = line.trim();
      const stageHeader = trimmed.match(
        /^(\*\*(?:Stage \d+|Additional Stage)[^*]*?):\s*\d+(?:\.\d+)?\s*\/\s*\d+\s*\*\*$/,
      );
      if (stageHeader) return `${stageHeader[1]}**`;
      if (
        /^\*\*(?:Total\s+Score|Score|Overall\s+Score)\b[^*]*?:\s*\d/.test(trimmed)
      ) {
        return "";
      }
      return line;
    })
    .filter((line) => line.trim() !== "")
    .join("\n");
}

type Props = {
  name: string;
  question: string;
  collectData: boolean | undefined;
};

const markdownComponents: Partial<Components> = {
  h1: ({ node, children }) => <Title order={1}>{children}</Title>,
  h2: ({ node, children }) => <Title order={2}>{children}</Title>,
  h3: ({ node, children }) => (
    <Title order={4} mb="md">
      {children}
    </Title>
  ),
  h4: ({ node, children }) => (
    <Title order={5} mb="xs">
      {children}
    </Title>
  ),
  p: ({ node, children }) => <Text size="sm">{children}</Text>,
  li: ({ node, children }) => (
    <Text size="sm" component="li" mb="xs">
      {children}
    </Text>
  ),
  strong: ({ node, children }) => <Text weight={700}>{children}</Text>,
};

function FormFieldFeedbackRenderer({ name, question, collectData }: Props) {
  const { getValues } = useFormContext<{ [name: string]: string }>();
  const feedbackContext = useContext(FeedbackContext);

  // PRD 20260824-playtest-score-visibility: students only see scores when the course
  // enables showAiScore; educators/admins always see the full feedback.
  const courseId = useGetCourseId();
  const accountType = useGetCurrentUserAccountType();
  const { data: course } = useGetSingleCourseQuery(courseId ?? "", {
    skip: !courseId,
  });
  const shouldHideScores =
    accountType === AccountType.Standard && course?.showAiScore === false;

  const [getFeedback, { isFetching, feedbackResult }] = useLazyGetFeedbackQuery(
    {
      selectFromResult: ({ isFetching, data: feedbackResult }) => ({
        isFetching,
        feedbackResult,
      }),
    },
  );

  const [tryStoreInitialResponse, { isLoading }] =
    useCreateInitialResponseIfNotExistsMutation({
      selectFromResult: ({ isLoading }) => ({ isLoading }),
    });

  const { resolveError } = useResolveError({
    name: "form-field-feedback-renderer",
  });

  const onGenerateFeedback = async () => {
    const content = getValues(name);
    if (isFetching || !content || isLoading) {
      return;
    }

    try {
      await getFeedback({
        content,
        submission_id: feedbackContext.submissionId,
        question,
      }).unwrap();
    } catch (error) {
      resolveError(error);
      return;
    }

    // If form in test mode, responses not considered
    if (feedbackContext.testMode || !feedbackContext.submissionId) {
      return;
    }

    const feedbackPostData = {
      submission_id: feedbackContext.submissionId,
      question,
      initial_response: content,
    };

    try {
      await tryStoreInitialResponse(feedbackPostData).unwrap();
    } catch (error) {
      resolveError(error);
    }
  };

  return (
    <Stack>
      <div>
        <Button
          leftIcon={<FaRegSmile />}
          compact
          loading={isFetching}
          onClick={onGenerateFeedback}
        >
          {isFetching ? "Generating" : "Generate"} feedback
        </Button>
      </div>

      {feedbackResult && (
        <Blockquote color="blue" mt="xl" icon={<TbMessageChatbot size={30} />}>
          <Paper withBorder shadow="xl" p="xl">
            <Text size="sm">
              Here is some feedback on what you have written:
              <br />
              <br />
            </Text>
            <Markdown components={markdownComponents}>
              {shouldHideScores
                ? stripScoresFromFeedbackMarkdown(feedbackResult.feedback ?? "")
                : feedbackResult.feedback}
            </Markdown>
          </Paper>
        </Blockquote>
      )}
    </Stack>
  );
}

export default FormFieldFeedbackRenderer;
