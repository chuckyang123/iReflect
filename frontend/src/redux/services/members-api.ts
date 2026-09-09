/**
 * @changelog
 * | Version | Description                                            | Reference                                     |
 * | v1.0.0 | Initial implementation (indexed baseline)              |                                               |
 * | v1.1.0 | Added batchImportCourseMemberships mutation            | REQ: 20260908-课程名单分组导入 TECH: 04_design_tech-design.md §3.3 |
 * /@changelog
 *
 * @author chuckyang123
 */
import baseApi from "./base-api";
import { cacher } from "./api-cache-utils";
import {
  CourseMemberData,
  CourseMembershipBatchCreateData,
  CourseMembershipPatchData,
  MembershipImportData,
  MembershipImportResult,
} from "../../types/courses";

const membersApi = baseApi
  .enhanceEndpoints({ addTagTypes: ["Member", "Group"] })
  .injectEndpoints({
    endpoints: (build) => ({
      getCourseMemberships: build.query<CourseMemberData[], number | string>({
        query: (courseId) => ({
          url: `/courses/${courseId}/memberships/`,
          method: "GET",
        }),
        providesTags: (result, _, courseId) =>
          cacher.providesList(result, "Member", [courseId]),
      }),

      updateCourseMembership: build.mutation<
        CourseMemberData,
        {
          courseId: number | string;
          membershipId: number;
        } & CourseMembershipPatchData
      >({
        query: ({ courseId, membershipId, ...courseMembershipPatchData }) => ({
          url: `/courses/${courseId}/memberships/${membershipId}/`,
          method: "PATCH",
          body: courseMembershipPatchData,
        }),
        invalidatesTags: (_, error, { membershipId: id, courseId }) =>
          error ? [] : [cacher.getIdTag(id, "Member", [courseId])],
      }),

      deleteCourseMembership: build.mutation<
        CourseMemberData,
        { courseId: number | string; membershipId: number }
      >({
        query: ({ courseId, membershipId }) => ({
          url: `/courses/${courseId}/memberships/${membershipId}/`,
          method: "DELETE",
        }),
        invalidatesTags: (_, error, { membershipId: id, courseId }) =>
          error ? [] : [cacher.getIdTag(id, "Member", [courseId])],
      }),

      batchCreateCourseMemberships: build.mutation<
        CourseMemberData[],
        CourseMembershipBatchCreateData & {
          courseId: number | string;
        }
      >({
        query: ({ courseId, ...courseMembershipBatchCreateData }) => ({
          url: `/courses/${courseId}/memberships/new`,
          method: "POST",
          body: courseMembershipBatchCreateData,
        }),
        invalidatesTags: (_, error, { courseId }) =>
          error ? [] : cacher.invalidatesList("Member", [courseId]),
      }),

      batchImportCourseMemberships: build.mutation<
        MembershipImportResult,
        MembershipImportData & { courseId: number | string }
      >({
        query: ({ courseId, ...membershipImportData }) => ({
          url: `/courses/${courseId}/memberships/import`,
          method: "POST",
          body: membershipImportData,
        }),
        invalidatesTags: (_, error, { courseId }) =>
          error
            ? []
            : [
                ...cacher.invalidatesList("Member", [courseId]),
                ...cacher.invalidatesList("Group", [courseId]),
              ],
      }),
    }),
  });

export const {
  useGetCourseMembershipsQuery,
  useUpdateCourseMembershipMutation,
  useDeleteCourseMembershipMutation,
  useBatchCreateCourseMembershipsMutation,
  useBatchImportCourseMembershipsMutation,
} = membersApi;
