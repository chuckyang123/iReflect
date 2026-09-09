/**
 * @changelog
 * | Version | Description                                            | Reference                                     |
 * | v1.0.0 | Initial implementation (indexed baseline)              |                                               |
 * | v1.1.0 | Rebuilt flow: optional group column, one-shot import with per-row results panel, error CSV copy/download and retry of failed rows | REQ: 20260908-课程名单分组导入 TECH: 04_design_tech-design.md §3.5.3 |
 * | v1.1.1 | Fix result panel Line mapping: remap submitted-subset row indices back to original file positions (skipped invalid rows and retry-only-failed submissions) | REQ: 20260908-课程名单分组导入 TECH: E2E-004 |
 * /@changelog
 *
 * @author chuckyang123
 */
import {
  Badge,
  Button,
  Group,
  Loader,
  ScrollArea,
  Stack,
  Table,
  Text,
} from "@mantine/core";
import { saveAs } from "file-saver";
import papaparse from "papaparse";
import { z } from "zod";
import { MdContentCopy, MdPersonAdd, MdReplay } from "react-icons/md";
import { RiFileDownloadLine } from "react-icons/ri";
import { useCallback, useState } from "react";
import toastUtils from "../utils/toast-utils";
import { useResolveError } from "../utils/error-utils";
import { useBatchImportCourseMembershipsMutation } from "../redux/services/members-api";
import { EMAIL, GROUP, NAME } from "../constants";
import type {
  MembershipImportResult,
  MembershipImportRowInput,
} from "../types/courses";
import CourseMemberCsvFileUploader from "./course-member-csv-file-uploader";

type Props = {
  courseId?: number | string;
  onSuccess?: () => void;
};

type MemberCreationCsvRowData = [string, string, string?];

const schema = z.object({
  [EMAIL]: z
    .string()
    .trim()
    .min(1, "Please enter an email address")
    .email("Invalid email address"),
  [NAME]: z.string(),
  [GROUP]: z.string(),
});

enum RowStatus {
  New = "NEW",
  Invalid = "INVALID",
  Success = "SUCCESS",
  Error = "ERROR",
}

const STATUS_LABEL: Record<RowStatus, string> = {
  [RowStatus.New]: "Pending",
  [RowStatus.Invalid]: "Invalid",
  [RowStatus.Success]: "Success",
  [RowStatus.Error]: "Error",
};

type TableRow = {
  [EMAIL]: string;
  [NAME]: string;
  [GROUP]: string;
  status: RowStatus;
  message?: string;
};

function getStatusColor(status: RowStatus): string {
  switch (status) {
    case RowStatus.Success:
      return "green";
    case RowStatus.Error:
    case RowStatus.Invalid:
      return "red";
    case RowStatus.New:
      return "yellow";
    default:
      return "";
  }
}

function CourseMemberCreationEditor({ courseId, onSuccess }: Props) {
  const [isParsingCSV, setIsParsingCSV] = useState(false);
  const [tableRows, setTableRows] = useState<TableRow[]>([]);
  const [importResult, setImportResult] = useState<MembershipImportResult | null>(
    null,
  );

  const { resolveError } = useResolveError();
  const [batchImportCourseMemberships, { isLoading: isSubmitting }] =
    useBatchImportCourseMembershipsMutation({
      selectFromResult: ({ isLoading }) => ({ isLoading }),
    });

  const onDownloadCsvTemplate = useCallback(() => {
    const ADD_MEMBERS_CSV_TEMPLATE = new Blob(
      [
        papaparse.unparse({
          fields: ["email", "name (optional)", "group (optional)"],
          data: [
            ["example@u.nus.edu", "Jeremy Tan", "Group 1"],
            ["another_example@comp.nus.edu.sg", "CYNTHIA LEE", "Group 2"],
            ["exxxxx@u.nus.edu.sg", "", ""],
          ],
        }),
      ],
      { type: "text/csv;charset=utf-8" },
    );

    saveAs(ADD_MEMBERS_CSV_TEMPLATE, "add course members template.csv");
  }, []);

  const updateRowsFromImportResult = (
    submittedIndices: number[],
    result: MembershipImportResult,
  ) => {
    setTableRows((prevRows) => {
      const nextRows = [...prevRows];
      result.rows.forEach((rowResult) => {
        const tableIndex = submittedIndices[rowResult.index];
        if (tableIndex === undefined || nextRows[tableIndex] === undefined) {
          return;
        }
        nextRows[tableIndex] = {
          ...nextRows[tableIndex],
          status:
            rowResult.status === "success" ? RowStatus.Success : RowStatus.Error,
          message:
            rowResult.status === "success"
              ? rowResult.message
              : `${rowResult.message} ${rowResult.suggestion}`.trim(),
        };
      });
      return nextRows;
    });
    // Response row indices are relative to the submitted payload, which may be
    // a subset of the original table (locally-invalid rows are skipped, and a
    // retry only resubmits the failed rows). Remap each index back to its
    // original table position so the "Line" column and per-row statuses keep
    // referring to the rows of the original file in every submission mode.
    const remappedResult: MembershipImportResult = {
      ...result,
      rows: result.rows.map((rowResult) => {
        const tableIndex = submittedIndices[rowResult.index];
        return tableIndex === undefined
          ? rowResult
          : { ...rowResult, index: tableIndex };
      }),
    };
    setImportResult(remappedResult);
  };

  const runImport = async (submittedIndices: number[]) => {
    if (courseId === undefined || submittedIndices.length === 0) {
      return;
    }

    const payloadRows: MembershipImportRowInput[] = submittedIndices.map(
      (tableIndex) => {
        const row = tableRows[tableIndex];
        return {
          [EMAIL]: row[EMAIL],
          [NAME]: row[NAME],
          ...(row[GROUP] ? { [GROUP]: row[GROUP] } : {}),
        };
      },
    );

    setImportResult(null);

    try {
      const result = await batchImportCourseMemberships({
        courseId,
        rows: payloadRows,
      }).unwrap();

      updateRowsFromImportResult(submittedIndices, result);

      const { summary } = result;
      toastUtils.success({
        message: `Import completed: ${summary.succeeded} succeeded, ${summary.failed} failed.`,
      });

      if (summary.failed === 0) {
        onSuccess?.();
      }
    } catch (error) {
      resolveError(error);
    }
  };

  const handleSubmit = async () => {
    const submittedIndices: number[] = [];
    tableRows.forEach((row, index) => {
      if (row.status === RowStatus.New) {
        submittedIndices.push(index);
      }
    });

    if (submittedIndices.length === 0) {
      toastUtils.info({ message: "No new members to add to the course." });
      return;
    }

    await runImport(submittedIndices);
  };

  const handleRetryFailedRows = async () => {
    const failedIndices: number[] = [];
    tableRows.forEach((row, index) => {
      if (row.status === RowStatus.Error) {
        failedIndices.push(index);
      }
    });

    if (failedIndices.length === 0) {
      return;
    }

    await runImport(failedIndices);
  };

  const parseCSVTemplate = (files: File[]) => {
    const csvFile = files[0];

    if (!csvFile) {
      return;
    }

    setIsParsingCSV(true);

    /* eslint-disable @typescript-eslint/no-unsafe-call */
    papaparse.parse<MemberCreationCsvRowData, papaparse.LocalFile>(csvFile, {
      worker: true,
      error: (error: { message: string }) => {
        console.log("Parse CSV file error:", error, error.message);
        toastUtils.error({ message: error.message });
      },
      complete: ({ data }) => {
        // removes column headers (email, name (optional), group (optional))
        data.shift();

        const parsedRows: TableRow[] = data.map((row) => {
          const parsedData: TableRow = {
            [EMAIL]: row[0] ?? "",
            [NAME]: row[1] ?? "",
            [GROUP]: row[2] ?? "",
            status: RowStatus.New,
          };

          try {
            schema.parse(parsedData);
          } catch (error) {
            parsedData.status = RowStatus.Invalid;
          }

          return parsedData;
        });

        setTableRows(parsedRows);
        setImportResult(null);

        toastUtils.info({
          message: "The CSV file content has been successfully parsed.",
        });
      },
    });
    /* eslint-enable @typescript-eslint/no-unsafe-call */

    setIsParsingCSV(false);
  };

  const clearData = () => {
    setTableRows([]);
    setImportResult(null);
  };

  const errorRows =
    importResult?.rows.filter((row) => row.status === "error") ?? [];
  const errorCount = errorRows.length;

  const buildErrorCsvString = () =>
    papaparse.unparse({
      fields: ["email", "name", "group", "error message", "suggestion"],
      data: errorRows.map((row) =>
        row.status === "error"
          ? [row.email, row.name, row.group, row.message, row.suggestion]
          : [],
      ),
    });

  const downloadErrorCsv = () => {
    if (errorCount === 0) {
      return;
    }
    const csv = new Blob([buildErrorCsvString()], {
      type: "text/csv;charset=utf-8",
    });
    saveAs(csv, "import errors.csv");
  };

  const copyErrors = async () => {
    if (errorCount === 0) {
      return;
    }
    try {
      await navigator.clipboard.writeText(buildErrorCsvString());
      toastUtils.success({ message: "Copied error list to clipboard." });
    } catch (error) {
      resolveError(error);
    }
  };

  const hasEmailData = tableRows.length !== 0;
  const { summary } = importResult ?? {};
  const showResultSummary = importResult !== null && summary !== undefined;

  return (
    <Stack>
      <Group position="apart">
        <Button
          onClick={onDownloadCsvTemplate}
          leftIcon={<RiFileDownloadLine />}
        >
          Download CSV template
        </Button>
        <Group hidden={!hasEmailData}>
          <Button
            onClick={clearData}
            disabled={isParsingCSV || isSubmitting}
            color="red"
          >
            Clear Data
          </Button>
          <Button
            onClick={handleSubmit}
            disabled={isParsingCSV || isSubmitting}
            leftIcon={
              isSubmitting ? <Loader size={14} /> : <MdPersonAdd size={14} />
            }
          >
            {isSubmitting ? "Importing..." : "Import Members"}
          </Button>
        </Group>
      </Group>

      {showResultSummary && (
        <Stack spacing="xs">
          <Group position="apart">
            <Text weight={700}>Import Result</Text>
            <Group hidden={errorCount === 0}>
              <Button
                variant="subtle"
                size="xs"
                leftIcon={<MdReplay size={14} />}
                onClick={handleRetryFailedRows}
                disabled={isSubmitting}
              >
                Retry Failed Rows
              </Button>
              <Button
                variant="subtle"
                size="xs"
                leftIcon={<MdContentCopy size={14} />}
                onClick={copyErrors}
                disabled={isSubmitting}
              >
                Copy Errors
              </Button>
              <Button
                variant="subtle"
                size="xs"
                leftIcon={<RiFileDownloadLine size={14} />}
                onClick={downloadErrorCsv}
                disabled={isSubmitting}
              >
                Download Errors (CSV)
              </Button>
            </Group>
          </Group>
          <Group spacing="xs">
            <Badge color="gray">Total: {summary?.total}</Badge>
            <Badge color="green">Succeeded: {summary?.succeeded}</Badge>
            <Badge color="red">Failed: {summary?.failed}</Badge>
            <Badge color="blue">Users created: {summary?.usersCreated}</Badge>
            <Badge color="blue">
              Memberships added: {summary?.membershipsCreated}
            </Badge>
            <Badge color="teal">Groups created: {summary?.groupsCreated}</Badge>
            <Badge color="teal">
              Group memberships: {summary?.groupMembershipsAdded}
            </Badge>
          </Group>
          {errorCount > 0 && (
            <ScrollArea style={{ height: 160 }}>
              <Table striped highlightOnHover fontSize="xs">
                <thead>
                  <tr>
                    <th>Line</th>
                    <th>Email</th>
                    <th>Name</th>
                    <th>Group</th>
                    <th>Error Message</th>
                    <th>Suggestion</th>
                  </tr>
                </thead>
                <tbody>
                  {errorRows.map((row) =>
                    row.status === "error" ? (
                      <tr key={`${row.index}-${row.email}`}>
                        <td>{row.index + 2}</td>
                        <td>{row.email}</td>
                        <td>{row.name}</td>
                        <td>{row.group}</td>
                        <td>{row.message}</td>
                        <td>{row.suggestion}</td>
                      </tr>
                    ) : null,
                  )}
                </tbody>
              </Table>
            </ScrollArea>
          )}
        </Stack>
      )}

      {hasEmailData ? (
        <ScrollArea style={{ height: 300 }}>
          <Table striped>
            <thead>
              <tr>
                <th>Email</th>
                <th>Name (Optional)</th>
                <th>Group (Optional)</th>
                <th>Status</th>
              </tr>
            </thead>

            <tbody>
              {tableRows.map((row, index) => (
                <tr key={`${row.email}-${index}`}>
                  <td>{row.email}</td>
                  <td>{row.name}</td>
                  <td>{row.group}</td>
                  <td>
                    <Group spacing="xs">
                      <Badge color={getStatusColor(row.status)}>
                        {STATUS_LABEL[row.status]}
                      </Badge>
                      {row.message && (
                        <Text
                          color="dimmed"
                          size="xs"
                          lineClamp={1}
                          style={{ maxWidth: 220 }}
                        >
                          {row.message}
                        </Text>
                      )}
                    </Group>
                  </td>
                </tr>
              ))}
            </tbody>
          </Table>
        </ScrollArea>
      ) : (
        <CourseMemberCsvFileUploader
          onDrop={parseCSVTemplate}
          isLoading={isParsingCSV}
        />
      )}
    </Stack>
  );
}

export default CourseMemberCreationEditor;
