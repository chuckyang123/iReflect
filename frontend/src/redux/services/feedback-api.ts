import {
  FeedbackData,
  FeedbackInitialResponseData,
  FeedbackInitialResponsePostData,
  FeedbackPostData,
  FeedbackRecordPostData,
  FeedbackRecordQueryParams,
  FeedbackRecordResponseData,
  FeedbackVersionHistoryData,
} from "../../types/feedback";
import baseApi from "./base-api";

const feedbackApi = baseApi.injectEndpoints({
  endpoints: (build) => ({
    getFeedback: build.query<FeedbackData, FeedbackPostData>({
      query: (data) => ({
        url: "/feedback/",
        method: "POST",
        body: data,
      }),
    }),
    createInitialResponseIfNotExists: build.mutation<
      FeedbackInitialResponseData,
      FeedbackInitialResponsePostData
    >({
      query: ({ ...feedbackPostData }) => ({
        url: "/feedback/initial-response/",
        method: "POST",
        body: feedbackPostData,
      }),
    }),
    createFeedbackRecord: build.mutation<
      FeedbackRecordResponseData,
      FeedbackRecordPostData
    >({
      query: ({ ...feedbackRecordPostData }) => ({
        url: "/feedback/records/",
        method: "POST",
        body: feedbackRecordPostData,
      }),
    }),
    getFeedbackAnswerVersions: build.query<
      FeedbackVersionHistoryData[],
      FeedbackRecordQueryParams
    >({
      query: (params) => ({
        url: "/feedback/records/",
        method: "GET",
        params,
      }),
    }),
  }),
});

export const {
  useLazyGetFeedbackQuery,
  useCreateInitialResponseIfNotExistsMutation,
  useCreateFeedbackRecordMutation,
  useGetFeedbackAnswerVersionsQuery,
} = feedbackApi;
