import { useContext } from "react";
import { Button, Stack, createStyles, Group, Text } from "@mantine/core";
import { FormProvider, useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import toastUtils from "../utils/toast-utils";
import { EMAIL, NAME, PASSWORD, REMEMBER_ME } from "../constants";
import TextField from "./text-field";
import PasswordField from "./password-field";
import { useAppDispatch, useAppSelector } from "../redux/hooks";
import { selectRememberMe } from "../redux/slices/remember-me-slice";
import CheckboxField from "./checkbox-field";
import loggedIn from "../redux/thunks/logged-in";
import {
  usePasswordLoginMutation,
  usePasswordResetMutation,
} from "../redux/services/auth-api";
import { handleSubmitForm } from "../utils/form-utils";
import { LoginContext } from "../contexts/login-provider";
import { useResolveError } from "../utils/error-utils";
import { emptySelector } from "../redux/utils";

const schema = z.object({
  [EMAIL]: z.string().trim().min(1).email(),
  [NAME]: z
    .string()
    .trim()
    .min(1, "Please enter your name")
    .refine((value) => !z.string().email().safeParse(value).success, {
      message: "Please enter your name and not email",
    }),
  [PASSWORD]: z.string().trim().min(1, "Please enter password"),
  [REMEMBER_ME]: z.boolean(),
});

type LoginAccountFormProps = z.infer<typeof schema>;

const DEFAULT_VALUES: LoginAccountFormProps = {
  name: "",
  email: "",
  password: "",
  rememberMe: true,
};

const useStyles = createStyles({
  emailButton: {
    alignSelf: "center",
  },
});

function LoginAccountForm() {
  const { classes } = useStyles();
  const rememberMe = useAppSelector(selectRememberMe);
  const dispatch = useAppDispatch();
  const [passwordLogin] = usePasswordLoginMutation({
    selectFromResult: emptySelector,
  });
  const [passwordReset] = usePasswordResetMutation({
    selectFromResult: emptySelector,
  });
  const {
    accountDetails: { name, email, isActivated } = {
      name: "",
      email: "",
      isActivated: false,
    },
    setAccountDetails,
  } = useContext(LoginContext);
  const methods = useForm<LoginAccountFormProps>({
    resolver: zodResolver(schema),
    defaultValues: { ...DEFAULT_VALUES, name, email, rememberMe },
  });
  const { resolveError } = useResolveError({ name: "login-account-form" });

  const {
    handleSubmit,
    formState: { isSubmitting },
  } = methods;

  const onSubmit = async (formData: LoginAccountFormProps) => {
    if (isSubmitting) {
      return;
    }

    const { rememberMe, ...passwordLoginPostData } = formData;

    const currentUser = await passwordLogin(passwordLoginPostData).unwrap();

    dispatch(loggedIn(currentUser, rememberMe));

    toastUtils.success({ message: "Signed in successfully." });
  };

  const resetPassword = async () => {
    try {
      await passwordReset({ email }).unwrap();
      toastUtils.success({
        message:
          "Password reset email sent. Check your email for the reset link.",
      });
    } catch (error) {
      resolveError(error);
    }
  };

  return (
    <FormProvider {...methods}>
      <form onSubmit={handleSubmitForm(handleSubmit(onSubmit), resolveError)}>
        <Stack spacing="lg">
          <Stack>
            <Text size="lg" weight={600} align="center">
              {isActivated ? `Hi, ${name}` : "Create New Account"}
            </Text>
            <Button
              size="xs"
              radius="xl"
              variant="outline"
              onClick={() => setAccountDetails(undefined)}
              className={classes.emailButton}
            >
              {email}
            </Button>

            {(!name || !isActivated) && (
              <TextField
                name={NAME}
                label="Full name"
                autoFocus
                autoComplete="name"
                disabled={Boolean(name)}
              />
            )}

            <PasswordField
              name={PASSWORD}
              label="Password"
              autoComplete={isActivated ? "current-password" : "new-password"}
              autoFocus={Boolean(name)}
            />

            <Group position="apart">
              <CheckboxField name={REMEMBER_ME} label="Remember me" />

              {isActivated && (
                <Button
                  size="xs"
                  variant="subtle"
                  onClick={() => resetPassword()}
                >
                  Forgot password?
                </Button>
              )}
            </Group>
          </Stack>

          <Button loading={isSubmitting} type="submit">
            {isActivated ? "Login" : "Sign up"}
          </Button>
        </Stack>
      </form>
    </FormProvider>
  );
}

export default LoginAccountForm;
