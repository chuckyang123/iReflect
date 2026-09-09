/**
 * @changelog
 * | Version | Description                                            | Reference                                     |
 * | v1.0.0 | Initial implementation (indexed baseline)              |                                               |
 * | v1.1.0 | CourseSettings type adds showAiScore field            | REQ: 20260824-playtest-score-visibility TECH: tech-design §4.2 |
 * | v1.2.0 | Added membership import request/result types          | REQ: 20260908-课程名单分组导入 TECH: 04_design_tech-design.md §3.3 |
 * /@changelog
 *
 * @author chuckyang123
 */
import {
  NAME,
  OWNER,
  DESCRIPTION,
  IS_PUBLISHED,
  SHOW_GROUP_MEMBERS_NAMES,
  ALLOW_STUDENTS_TO_CREATE_GROUPS,
  ALLOW_STUDENTS_TO_DELETE_GROUPS,
  ALLOW_STUDENTS_TO_JOIN_GROUPS,
  ALLOW_STUDENTS_TO_LEAVE_GROUPS,
  ALLOW_STUDENTS_TO_MODIFY_GROUP_NAME,
  ALLOW_STUDENTS_TO_ADD_OR_REMOVE_GROUP_MEMBERS,
  MILESTONE_ALIAS,
  SHOW_AI_SCORE,
  ROLE,
  OWNER_ID,
  USER,
  MEMBER_CREATION_DATA,
  EMAIL,
  GROUP,
} from "../constants";
import { BaseData } from "./base";
import { UserData } from "./users";

export enum Role {
  CoOwner = "CO-OWNER",
  Instructor = "INSTRUCTOR",
  Student = "STUDENT",
}

export const ALL_ROLES = Object.values(Role);

export const roleToPropertiesMap = {
  [Role.CoOwner]: {
    label: "Co-Owner",
    permissionRoles: [Role.CoOwner],
    modifiableRoles: ALL_ROLES,
  },
  [Role.Instructor]: {
    label: "Instructor",
    permissionRoles: [Role.Instructor, Role.CoOwner],
    modifiableRoles: [Role.Student, Role.Instructor],
  },
  [Role.Student]: {
    label: "Student",
    permissionRoles: ALL_ROLES,
    modifiableRoles: [Role.Student],
  },
};

export type CourseSummaryData = BaseData & {
  [NAME]: string;
  [OWNER]: UserData;
  [DESCRIPTION]: string;
  [IS_PUBLISHED]: boolean;
  [ROLE]: Role;
};

type CourseSettings = {
  [SHOW_GROUP_MEMBERS_NAMES]: boolean;
  [ALLOW_STUDENTS_TO_CREATE_GROUPS]: boolean;
  [ALLOW_STUDENTS_TO_DELETE_GROUPS]: boolean;
  [ALLOW_STUDENTS_TO_JOIN_GROUPS]: boolean;
  [ALLOW_STUDENTS_TO_LEAVE_GROUPS]: boolean;
  [ALLOW_STUDENTS_TO_MODIFY_GROUP_NAME]: boolean;
  [ALLOW_STUDENTS_TO_ADD_OR_REMOVE_GROUP_MEMBERS]: boolean;
  [MILESTONE_ALIAS]: string;
  [SHOW_AI_SCORE]: boolean;
};

export type CourseData = CourseSummaryData & CourseSettings;

export type CoursePostData = Pick<
  CourseSummaryData,
  typeof NAME | typeof DESCRIPTION | typeof IS_PUBLISHED
> &
  CourseSettings;

export type CoursePutData = CoursePostData & {
  [OWNER_ID]?: number;
};

export type CourseMemberData = BaseData & {
  [ROLE]: Role;
  [USER]: UserData;
};

export type CourseMembershipPatchData = {
  [ROLE]: Role;
};

export type MemberCreationData = {
  [EMAIL]: string;
  [NAME]: string;
};

export type CourseMembershipBatchCreateData = {
  [MEMBER_CREATION_DATA]: MemberCreationData[];
};

export type MembershipImportRowInput = {
  [EMAIL]: string;
  [NAME]?: string;
  [GROUP]?: string;
};

export type MembershipImportData = {
  rows: MembershipImportRowInput[];
};

export type MembershipImportSummary = {
  total: number;
  succeeded: number;
  failed: number;
  usersCreated: number;
  membershipsCreated: number;
  groupsCreated: number;
  groupMembershipsAdded: number;
};

export type MembershipImportSuccessRow = {
  index: number;
  email: string;
  name: string;
  group: string;
  status: "success";
  code: string;
  message: string;
  data: {
    userCreated: boolean;
    membershipCreated: boolean;
    groupCreated: boolean;
    groupJoined: boolean;
    groupName: string;
  };
};

export type MembershipImportErrorRow = {
  index: number;
  email: string;
  name: string;
  group: string;
  status: "error";
  code: string;
  message: string;
  suggestion: string;
};

export type MembershipImportRowResult =
  | MembershipImportSuccessRow
  | MembershipImportErrorRow;

export type MembershipImportResult = {
  summary: MembershipImportSummary;
  rows: MembershipImportRowResult[];
};
