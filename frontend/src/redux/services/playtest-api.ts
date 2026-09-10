import { createApi, fetchBaseQuery } from "@reduxjs/toolkit/query/react";
import { PlaytestPostData, PlaytestResponseData } from "../../types/feedback";
import baseApi from "./base-api";

const playtestApi = createApi({
  reducerPath: "playtestApi",
  baseQuery: fetchBaseQuery({ baseUrl: "" }),
  endpoints: (build) => ({
    getFeedback: build.query<PlaytestResponseData, PlaytestPostData>({
      query: (data) => ({
        url: "/api/playtest/",
        method: "POST",
        body: data,
      }),
    }),
  }),
});

export const { useLazyGetFeedbackQuery } = playtestApi;
// export default playtestApi;
