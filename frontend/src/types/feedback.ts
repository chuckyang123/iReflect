import {
  ANNOTATED_CONTENT,
  ANSWER_CONTENT,
  CONTENT,
  CREATED,
  FEEDBACK,
  FEEDBACK_CONTENT,
  FEEDBACK_RECORDS,
  IDEMPOTENCY_KEY,
  INITIAL_RESPONSE,
  QUESTION,
  GENRE,
  MECHANIC,
  RECORD_ID,
  SUBMISSION,
  SUBMISSION_ID,
  VERSION_NUMBER,
  PLAYTEST_MODE,
  PLAYTEST_RESPONSE,
  PLAYTEST_QUERY,
} from "../constants";
import { BaseData } from "./base";

export type FeedbackData = {
  [ANNOTATED_CONTENT]: string;
  [FEEDBACK]: string;
  [RECORD_ID]?: string | number | null;
};

export type FeedbackPostData = {
  [CONTENT]: string;
  [SUBMISSION_ID]?: string | number;
  [QUESTION]?: string;
};

export type FeedbackInitialResponseData = {
  [CREATED]: boolean;
  [INITIAL_RESPONSE]: string;
};

export type FeedbackInitialResponsePostData = Partial<BaseData> & {
  [SUBMISSION_ID]: string | number;
  [QUESTION]: string;
  [GENRE]?: string;
  [MECHANIC]?: string;
  [INITIAL_RESPONSE]: string;
};

export type FeedbackRecordPostData = {
  [SUBMISSION_ID]: string | number;
  [QUESTION]: string;
  [INITIAL_RESPONSE]: string;
  [FEEDBACK_CONTENT]: string;
  [GENRE]?: string;
  [MECHANIC]?: string;
  [IDEMPOTENCY_KEY]?: string;
};

export type FeedbackRecordResponseData = {
  record: {
    id: string | number;
    [FEEDBACK_CONTENT]: string;
  };
  version: {
    id: string | number;
    version_number: number;
    [INITIAL_RESPONSE]: string;
  };
};

export type PlaytestPostData = {
  [PLAYTEST_QUERY]: string;
  [PLAYTEST_MODE]: string;
};

export type PlaytestResponseData = {
  [PLAYTEST_RESPONSE]: string;
};

export type FeedbackAnswerVersionData = BaseData & {
  name: string;
  [QUESTION]: string;
  [ANSWER_CONTENT]: string;
  [VERSION_NUMBER]: number;
  [GENRE]?: string | null;
  [MECHANIC]?: string | null;
  creator?: {
    id: string | number;
    name: string;
    email: string;
    profile_image?: string | null;
    account_type?: string;
    is_activated?: boolean;
  } | null;
  milestone?: { id: string | number; name: string } | null;
  course?: { id: string | number; name: string } | null;
  [SUBMISSION]?: { id: string | number; name: string } | null;
};

export type AIFeedbackRecordData = BaseData & {
  version: FeedbackAnswerVersionData;
  feedback_type: string;
  strategy: string;
  score_json: Record<string, unknown> | null;
  [FEEDBACK_CONTENT]?: string;
  // camelCase response field rendered by the DRF CamelCase renderer.
  feedbackContent: string;
  model_version?: string | null;
  token_usage_json?: Record<string, unknown> | null;
  latency_ms?: number | null;
};

export type FeedbackVersionHistoryData = FeedbackAnswerVersionData & {
  [FEEDBACK_RECORDS]: AIFeedbackRecordData[];
};

export type FeedbackRecordQueryParams = {
  [SUBMISSION_ID]?: string | number;
  course_id?: string | number;
  user_id?: string | number;
  milestone_id?: string | number;
  [QUESTION]?: string;
};
