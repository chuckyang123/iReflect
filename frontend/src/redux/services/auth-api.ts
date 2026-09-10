/**
 * @changelog
 * | Version | Description                                                                  | Reference                                      |
 * | v1.0.0 | Initial implementation: authentication endpoints                             |                                                |
 * | v1.1.0 | passwordReset converted from query to mutation so repeated clicks actually re-send the request (RTK Query caches queries) | REQ: 20260904-password-reset-flow |
 * /@changelog
 *
 * @author chuckyang123
 */
import baseApi from "./base-api";
import {
  AuthenticationData,
  AccountDetails,
  PasswordLoginPostData,
  CheckAccountPostData,
  PasswordResetDetails,
  PasswordResetPostData,
} from "../../types/auth";

const authApi = baseApi.injectEndpoints({
  endpoints: (build) => ({
    checkAccount: build.query<AccountDetails, CheckAccountPostData>({
      query: (data) => ({
        url: "/gateway/check/",
        method: "POST",
        body: data,
      }),
      extraOptions: { includeAuth: false },
    }),
    passwordLogin: build.mutation<AuthenticationData, PasswordLoginPostData>({
      query: (data) => ({
        url: "/gateway/login/",
        method: "POST",
        body: data,
      }),
      extraOptions: { includeAuth: false },
    }),
    passwordReset: build.mutation<PasswordResetDetails, CheckAccountPostData>({
      query: (data) => ({
        url: "/gateway/reset/",
        method: "POST",
        body: data,
      }),
      extraOptions: { includeAuth: false },
    }),
    passwordResetConfirm: build.mutation<
      PasswordResetDetails,
      PasswordResetPostData
    >({
      query: (data) => ({
        url: "/gateway/reset-confirm/",
        method: "POST",
        body: data,
      }),
      extraOptions: { includeAuth: false },
    }),
  }),
});

export const {
  usePasswordResetConfirmMutation,
  usePasswordResetMutation,
  usePasswordLoginMutation,
  useLazyCheckAccountQuery,
} = authApi;
