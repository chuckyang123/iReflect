import { createStyles, Group, ScrollArea, Stack, Select } from "@mantine/core";
import { Controller, useFormContext } from "react-hook-form";
import { FormField, FormFieldType } from "../types/templates";
import CheckboxGroupField from "./checkbox-group-field";
import FormFieldCommentButton from "./form-field-comment-button";
import FormFieldFeedbackRenderer from "./form-field-feedback-renderer";
import FormFieldPlaytestFeedbackRenderer from "./form-field-playtest-feedback-renderer";
import NumericField from "./numeric-field";
import RadioGroupField from "./radio-group-field";
import TextField from "./text-field";
import TextViewer from "./text-viewer";
import TextareaField from "./textarea-field";

const useStyles = createStyles({
  // NOTE: currently there is no way to access the container for checkbox and radio options
  // use this hack for now
  optionsContainer: {
    "> .mantine-Group-root": {
      columnGap: "40px",
    },
  },
});

const genreOptions = [
  { value: "RPG", label: "Role Playing Game (RPG)" },
  { value: "Action", label: "Action" },
  { value: "Ddventure", label: "Adventure" },
  { value: "Simulation", label: "Simulation" },
  { value: "Strategy", label: "Strategy" },
  { value: "Sports", label: "Sports" },
  { value: "Educational/Scientific", label: "Educational/Scientific" },
  { value: "Puzzle", label: "Puzzle" },
];

const mechanicOptions = [
  { value: "Mobility & Movement", label: "Mobility & Movement" },
  { value: "Combat & Attack", label: "Combat & Attack" },
  {
    value: "Resource Management & Economy",
    label: "Resource Management & Economy",
  },
  { value: "Puzzle & Interaction", label: "Puzzle & Interaction" },
  { value: "AI & Character Interaction", label: "AI & Character Interaction" },
  { value: "Progression & Upgrade", label: "Progression & Upgrade" },
  { value: "Environmental Interaction", label: "Environmental Interaction" },
  { value: "Multiplayer & Social", label: "Multiplayer & Social" },
];

type Props = {
  name: string;
  formField: FormField;
  index: number;
  readOnly?: boolean;
  withComments?: boolean;
};

function FormFieldRenderer({
  name,
  formField,
  index,
  readOnly,
  withComments,
}: Props) {
  const { classes } = useStyles();

  const { control } = useFormContext();
  const genreDropdownComponent = (() => {
    if (
      formField.type !== FormFieldType.TextArea ||
      !formField.hasPlaytestFeedback
    ) {
      return null;
    }

    return (
      <Controller
        name="Genre"
        control={control}
        rules={{ required: true }}
        render={({ field }) => (
          <Select
            label="Select the Genre of the game you are playtesting"
            placeholder="Select genre"
            data={genreOptions}
            required
            {...field}
          />
        )}
      />
    );
  })();

  const mechanicDropdownComponent = (() => {
    if (
      formField.type !== FormFieldType.TextArea ||
      !formField.hasPlaytestFeedback
    ) {
      return null;
    }

    return (
      <Controller
        name="Mechanic"
        control={control}
        rules={{ required: true }}
        render={({ field }) => (
          <Select
            label="Select the MAIN Mechanic of the game you are playtesting"
            placeholder="Select MAIN mechanic"
            data={mechanicOptions}
            required
            {...field}
          />
        )}
      />
    );
  })();

  // PRD 20260901: when any AI feedback is enabled (regular or playtest), ask
  // the student why they stopped generating further AI feedback and finalized
  // their answer. The question is optional.
  const finalizationReasonComponent = (() => {
    if (
      formField.type !== FormFieldType.TextArea ||
      (!formField.hasFeedback && !formField.hasPlaytestFeedback)
    ) {
      return null;
    }

    return (
      <TextareaField
        name="FinalizationReason"
        label={
          <TextViewer
            span
            preserveWhiteSpace
            overflowWrap
            withLinkify
            inherit
          >
            In the previous interaction with AI feedback, why did you stop
            generating further feedback and finalize it?
          </TextViewer>
        }
        minRows={2}
        maxRows={5}
      />
    );
  })();

  const mainComponent = (() => {
    switch (formField.type) {
      case FormFieldType.Text: {
        const { label, description, placeholder, required } = formField;
        return (
          <TextField
            name={name}
            label={
              <TextViewer
                span
                preserveWhiteSpace
                overflowWrap
                withLinkify
                inherit
              >
                {label}
              </TextViewer>
            }
            description={
              <TextViewer
                span
                preserveWhiteSpace
                overflowWrap
                withLinkify
                inherit
              >
                {description}
              </TextViewer>
            }
            placeholder={placeholder}
            required={required}
            readOnly={readOnly}
          />
        );
      }
      case FormFieldType.TextArea: {
        const { label, description, placeholder, required } = formField;
        return (
          <TextareaField
            name={name}
            label={
              <TextViewer
                span
                preserveWhiteSpace
                overflowWrap
                withLinkify
                inherit
              >
                {label}
              </TextViewer>
            }
            description={
              <TextViewer
                span
                preserveWhiteSpace
                overflowWrap
                withLinkify
                inherit
              >
                {description}
              </TextViewer>
            }
            placeholder={placeholder}
            required={required}
            minRows={5}
            maxRows={20}
            readOnly={readOnly}
          />
        );
      }
      case FormFieldType.Numeric: {
        const { label, description, placeholder, required } = formField;
        return (
          <NumericField
            name={name}
            label={
              <TextViewer
                span
                preserveWhiteSpace
                overflowWrap
                withLinkify
                inherit
              >
                {label}
              </TextViewer>
            }
            description={
              <TextViewer
                span
                preserveWhiteSpace
                overflowWrap
                withLinkify
                inherit
              >
                {description}
              </TextViewer>
            }
            placeholder={placeholder}
            required={required}
            hideControls
            readOnly={readOnly}
          />
        );
      }
      case FormFieldType.Mcq: {
        const { label, description, required, choices } = formField;

        return (
          <RadioGroupField
            name={name}
            label={
              <TextViewer
                span
                preserveWhiteSpace
                overflowWrap
                withLinkify
                inherit
              >
                {label}
              </TextViewer>
            }
            description={
              <TextViewer
                span
                preserveWhiteSpace
                overflowWrap
                withLinkify
                inherit
              >
                {description}
              </TextViewer>
            }
            required={required}
            choices={choices}
            className={classes.optionsContainer}
            readOnly={readOnly}
          />
        );
      }
      case FormFieldType.Mrq: {
        const { label, description, required, choices } = formField;

        return (
          <CheckboxGroupField
            name={name}
            label={
              <TextViewer
                span
                preserveWhiteSpace
                overflowWrap
                withLinkify
                inherit
              >
                {label}
              </TextViewer>
            }
            description={
              <TextViewer
                span
                preserveWhiteSpace
                overflowWrap
                withLinkify
                inherit
              >
                {description}
              </TextViewer>
            }
            required={required}
            choices={choices}
            className={classes.optionsContainer}
            readOnly={readOnly}
          />
        );
      }
      case FormFieldType.TextDisplay: {
        const { content } = formField;

        return (
          <ScrollArea.Autosize
            offsetScrollbars
            maxHeight="200px"
            type="auto"
            scrollbarSize={8}
          >
            <TextViewer size="sm" preserveWhiteSpace overflowWrap withLinkify>
              {content}
            </TextViewer>
          </ScrollArea.Autosize>
        );
      }
      default:
        return null;
    }
  })();

  const feedbackComponent = (() => {
    if (formField.type !== FormFieldType.TextArea || !formField.hasFeedback) {
      return null;
    }

    return (
      <FormFieldFeedbackRenderer
        name={name}
        question={formField.label}
        collectData={formField.collectData}
      />
    );
  })();

  const playtestComponent = (() => {
    if (
      formField.type !== FormFieldType.TextArea ||
      !formField.hasPlaytestFeedback
    ) {
      return null;
    }

    return (
      <FormFieldPlaytestFeedbackRenderer
        name={name}
        question={formField.label}
        collectData={formField.collectData}
      />
    );
  })();

  return mainComponent ? (
    <Stack spacing={8}>
      {genreDropdownComponent}
      {mechanicDropdownComponent}
      {mainComponent}
      {withComments && (
        <Group position="right">
          <FormFieldCommentButton fieldIndex={index} />
        </Group>
      )}
      {feedbackComponent}
      {playtestComponent}
      {finalizationReasonComponent}
    </Stack>
  ) : null;
}

export default FormFieldRenderer;
