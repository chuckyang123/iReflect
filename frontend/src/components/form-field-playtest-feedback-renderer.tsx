import { Button, Text, Stack, Paper, Blockquote, Title } from "@mantine/core";
import { useFormContext } from "react-hook-form";
import { IoGameControllerOutline } from "react-icons/io5";
import { TbMessageChatbot } from "react-icons/tb";
import { useContext, useState, useEffect } from "react";
import Markdown, { Components } from "react-markdown";
/**
 * @changelog
 * | Version | Description                                            | Reference                                     |
 * | v1.0.0 | Initial implementation (indexed baseline)              |                                               |
 * | v1.1.0 | Student-side score stripping: stripScoresFromMarkdown + showAiScore integration | REQ: 20260824-playtest-score-visibility TECH: tech-design §4.4 |
 * | v1.2.0 | Playtest request uses absolute API URL; abort empty record creation on failure | DEV: fix HTML-in-JSON & blank feedbackContent |
 * /@changelog
 *
 * @author chuckyang123
 */
import { useResolveError } from "../utils/error-utils";
import {
  useCreateFeedbackRecordMutation,
  useCreateInitialResponseIfNotExistsMutation,
} from "../redux/services/feedback-api";
import { FeedbackContext } from "../contexts/feedback-data-collection-provider";
import useGetCourseId from "../custom-hooks/use-get-course-id";
import { useGetSingleCourseQuery } from "../redux/services/courses-api";
import useGetCurrentUserAccountType from "../custom-hooks/use-get-current-user-account-type";
import { AccountType } from "../types/users";

type Props = {
  name: string;
  question: string;
  collectData: boolean | undefined;
};

/**
 * Strip the numeric scoring block from LightRAG playtest feedback markdown.
 *
 * The LightRAG output follows `prompt_for_playtest_feedback.txt`:
 *   **Score: [xx/100]** → **Breakdown of Key Ingredients:** (10 x [x/10])
 *   → **Genre & Mechanic Evaluation (Knowledge Graph Score):** ([x/50])
 *   → **Professor Feedback:** (text) → **Final Summary:** (text)
 *
 * PRD 20260824-playtest-score-visibility hides all numeric scores from students, so
 * everything before "**Professor Feedback:**" is dropped. If the anchor is
 * missing (format drift, RISK-R1), fall back to line-based filtering.
 */
export function stripScoresFromMarkdown(markdown: string): string {
  const professorAnchor = "**Professor Feedback:**";
  const anchorIndex = markdown.indexOf(professorAnchor);
  if (anchorIndex !== -1) {
    return markdown.slice(anchorIndex).trim();
  }

  return markdown
    .split("\n")
    .filter((line) => {
      const trimmed = line.trim();
      // Total score line: **Score: [xx/100]**
      if (/^\*\*Score:\s*\[\d+\/\d+\]\*\*$/.test(trimmed)) return false;
      // Ingredient lines: - **Specificity:** [x/10] – ...
      if (/^[-*]\s+\*\*[^*]+:\*\*\s+\[\d+\/\d+\]/.test(trimmed)) return false;
      // Knowledge graph line: - **[x/50]** – ...
      if (/^[-*]\s+\*\*\[\d+\/\d+\]\*\*/.test(trimmed)) return false;
      // Section headers for the scoring block
      if (
        /^\*\*(Breakdown of Key Ingredients|Genre & Mechanic Evaluation)/.test(
          trimmed,
        )
      ) {
        return false;
      }
      return true;
    })
    .join("\n")
    .trim();
}

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

function FormFieldPlaytestFeedbackRenderer({
  name,
  question,
  collectData,
}: Props) {
  // const { getValues } = useFormContext<{ [name: string]: string }>();
  const { getValues } = useFormContext();
  const { resolveError } = useResolveError({
    name: "form-field-playtest-feedback-renderer",
  });
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

  const [isFetching, setisFetching] = useState(false);
  const [feedback, setFeedback] = useState<string | null>(null);
  const [promptText, setPromptText] = useState<string>("");
  const [inputError, setInputError] = useState<string | null>(null);

  useEffect(() => {
    const fetchPrompt = async () => {
      try {
        const res = await fetch("/prompt_for_playtest_feedback.txt");
        const text = await res.text();
        // Guard against the dev-server rewrite returning index.html instead
        // of the prompt file.
        setPromptText(text.trimStart().startsWith("<!DOCTYPE") ? "" : text);
      } catch (error) {
        console.error("Failed to load prompt file:", error);
      }
    };
    fetchPrompt();
  }, []);

  const [tryStoreInitialResponse, { isLoading }] =
    useCreateInitialResponseIfNotExistsMutation({
      selectFromResult: ({ isLoading }) => ({ isLoading }),
    });

  const [createFeedbackRecord] = useCreateFeedbackRecordMutation();

  const onGenerateFeedback = async () => {
    setInputError(null);
    const content = getValues(name) as string;
    const genre = getValues("Genre") as string;
    const mechanic = getValues("Mechanic") as string;
    console.log("genre:", genre, "mechanic:", mechanic);
    if (!genre || !mechanic) {
      setInputError(
        "Please select both a genre and a mechanic before generating feedback.",
      );
      return;
    }
    if (!content || isFetching || isLoading) return;

    const fullQuery = `
      ${promptText}
      Genre: ${genre}
      Main Mechanic: ${mechanic}
      Question: ${question}
      Answer: ${content}
    `;

    let playtestResponse = "";
    try {
      setisFetching(true);
      const res = await fetch(
        `${process.env.NEXT_PUBLIC_API_URL ?? ""}/playtest/`,
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "X-API-Key": "your-secure-api-key-here",
          },
          body: JSON.stringify({ query: fullQuery, mode: "hybrid" }),
        },
      );
      if (!res.ok) {
        throw new Error(`Playtest request failed: HTTP ${res.status}`);
      }

      const raw = (await res.json()) as { response?: string };
      playtestResponse = raw.response ?? "No feedback returned.";
      setFeedback(
        shouldHideScores
          ? stripScoresFromMarkdown(playtestResponse)
          : playtestResponse,
      );
    } catch (err) {
      resolveError(err);
      return; // abort: do not record an empty AI feedback entry (RISK-DA006)
    } finally {
      setisFetching(false);
    }

    // If form in test mode, responses not considered
    if (feedbackContext.testMode || !feedbackContext.submissionId) {
      return;
    }

    const feedbackPostData = {
      submission_id: feedbackContext.submissionId,
      question,
      genre,
      mechanic,
      initial_response: content,
    };

    try {
      await tryStoreInitialResponse(feedbackPostData).unwrap();
      console.log("Saved initial response:", feedbackPostData);
    } catch (error) {
      resolveError(error);
    }

    // Report the AI feedback record (idempotency key prevents duplicates, RISK-DA006)
    try {
      await createFeedbackRecord({
        submission_id: feedbackContext.submissionId,
        question,
        genre,
        mechanic,
        initial_response: content,
        feedback_content: playtestResponse,
        idempotency_key: crypto.randomUUID(),
      }).unwrap();
      console.log("Saved feedback record.");
    } catch (error) {
      resolveError(error);
    }
  };

  return (
    <Stack>
      <div>
        <Button
          leftIcon={<IoGameControllerOutline />}
          compact
          loading={isFetching}
          onClick={onGenerateFeedback}
        >
          {isFetching ? "Generating" : "Generate"} feedback
        </Button>
      </div>
      {inputError && (
        <Text color="red" mt="sm" size="sm">
          {inputError}
        </Text>
      )}
      {feedback && (
        <Blockquote color="blue" mt="xl" icon={<TbMessageChatbot size={30} />}>
          <Paper withBorder shadow="xl" p="xl">
            <Text size="sm">
              Here is some feedback on what you have written:
              <br />
              <br />
            </Text>
            <Markdown components={markdownComponents}>{feedback}</Markdown>
          </Paper>
        </Blockquote>
      )}
    </Stack>
  );
}

export default FormFieldPlaytestFeedbackRenderer;
