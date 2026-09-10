import { Textarea, TextareaProps } from "@mantine/core";
import { get, RegisterOptions, useFormContext } from "react-hook-form";

type Props = TextareaProps & {
  name: string;
  rules?: RegisterOptions;
};

function TextareaField({ name, required, rules, ...props }: Props) {
  const {
    formState: { errors },
    register,
  } = useFormContext();

  const error = get(errors, name);

  return (
    <Textarea
      withAsterisk={required}
      {...props}
      error={error?.message}
      {...register(name, rules)}
    />
  );
}

export default TextareaField;
