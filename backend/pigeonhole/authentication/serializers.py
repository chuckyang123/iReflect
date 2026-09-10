"""
@changelog
| Version | Description                                                                 | Reference                                      |
| v1.0.0  | Initial implementation: authentication serializers                          |                                                |
| v1.1.0  | Password-reset confirmation email is best-effort; failure no longer turns a successful reset into a 500 | REQ: 20260904-password-reset-flow |
/@changelog

@author chuckyang123
"""
from datetime import datetime
import os
import requests
import logging

from rest_framework import serializers
from rest_framework.exceptions import AuthenticationFailed

from rest_framework_simplejwt.serializers import TokenRefreshSerializer
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.settings import api_settings


from pigeonhole.common.constants import (
    NAME,
    EMAIL,
    REFRESH,
    TOKEN_ID,
    ACCESS_TOKEN,
    PASSWORD,
    USER,
    TOKENS,
    IS_ACTIVATED,
)
from pigeonhole.common.exceptions import InternalServerError, BadRequest
from users.models import User
from users.logic import requester_to_json, get_users

from email_service.logic import send_password_reset_mail, send_password_reset_confirmation_mail
from .logic import get_authenticated_data, reset_password

from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail
from django.utils.http import urlsafe_base64_encode, urlsafe_base64_decode
from authentication.tokens import default_token_generator

from .models import (
    AuthenticationData,
    GoogleAuthenticationData,
    FacebookAuthenticationData,
    PasswordAuthenticationData,
)

logger = logging.getLogger("main")


class GoogleAuthenticationSerializer(serializers.Serializer):
    token_id = serializers.CharField(required=True)

    def validate(self, data):
        token_id = data[TOKEN_ID]

        params = {"id_token": token_id}

        response = requests.get(
            url="https://oauth2.googleapis.com/tokeninfo",
            params=params,
        )
        response_data = response.json()

        name = response_data.get("name", "")
        email = response_data.get("email", "")
        auth_id = response_data.get("sub", "")

        if not all((name, email, auth_id)):
            raise BadRequest(detail="Invalid google token.")

        auth_data = GoogleAuthenticationData(
            name=name,
            email=email,
            auth_id=auth_id,
            profile_image=response_data.get("picture", ""),
        )

        return auth_data


FACEBOOK_APP_ID = os.getenv("FACEBOOK_APP_ID")
FACEBOOK_APP_SECRET = os.getenv("FACEBOOK_APP_SECRET")
VALID_SCOPES = {"email", "public_profile"}


class FacebookAuthenticationSerializer(serializers.Serializer):
    access_token = serializers.CharField(required=True)

    def verify_access_token(self, access_token: str):
        params = {
            "input_token": access_token,
            "access_token": f"{FACEBOOK_APP_ID}|{FACEBOOK_APP_SECRET}",
        }

        response = requests.get(
            url="https://graph.facebook.com/v11.0/debug_token",
            params=params,
        )

        response_data = response.json()

        data = response_data.get("data")

        if data is None:
            try:
                error_message = response_data.get("error").get("message")

                if not error_message:
                    raise ValueError("Empty error message.")
            except Exception as e:
                logger.warning(e)
                raise BadRequest(detail="Invalid facebook token.")

            raise InternalServerError(detail=error_message)

        app_id = data.get("app_id")
        is_valid = data.get("is_valid")
        scopes = set(data.get("scopes", []))

        if app_id != FACEBOOK_APP_ID or not is_valid or scopes != VALID_SCOPES:
            raise BadRequest(detail="Invalid facebook token.")

    def validate(self, data):
        access_token = data[ACCESS_TOKEN]

        self.verify_access_token(access_token)

        params = {
            "fields": "id,name,email,picture.width(512).height(512)",
            "access_token": access_token,
        }

        response = requests.get(
            url="https://graph.facebook.com/v11.0/me",
            params=params,
        )
        response_data = response.json()

        name = response_data.get("name", "")
        email = response_data.get("email", "")
        auth_id = response_data.get("id", "")

        if not all((name, email, auth_id)):
            raise BadRequest(detail="Invalid facebook token.")

        try:
            profile_image = response_data.get("picture").get("data").get("url", "")
        except Exception as e:
            logger.warning(e)
            profile_image = ""

        auth_data = FacebookAuthenticationData(
            name=name,
            email=email,
            auth_id=auth_id,
            profile_image=profile_image,
        )

        return auth_data


class PasswordAuthenticationSerializer(serializers.Serializer):
    password = serializers.CharField(required=True)

    def validate(self, data):
        password = data[PASSWORD]

        auth_data = PasswordAuthenticationData(
            name="",
            email="",
            auth_id=password,
        )

        return auth_data


class BaseAuthenticationSerializer(serializers.Serializer):
    def raise_invalid_user(self):
        raise AuthenticationFailed(detail="Invalid user.")

    def authenticate(self, auth_data: AuthenticationData) -> dict:
        authenticated_user = auth_data.authenticate()

        if authenticated_user is None:
            self.raise_invalid_user()

        return get_authenticated_data(user=authenticated_user)


class GoogleLoginSerializer(
    GoogleAuthenticationSerializer, BaseAuthenticationSerializer
):
    def validate(self, data):
        try:
            auth_data = super().validate(data)
        except BadRequest as e:
            logger.warning(e)
            self.raise_invalid_user()

        return self.authenticate(auth_data)


class FacebookLoginSerializer(
    FacebookAuthenticationSerializer, BaseAuthenticationSerializer
):
    def validate(self, data):
        try:
            auth_data = super().validate(data)
        except BadRequest as e:
            logger.warning(e)
            self.raise_invalid_user()

        return self.authenticate(auth_data)


class PasswordLoginSerializer(
    PasswordAuthenticationSerializer, BaseAuthenticationSerializer
):
    name = serializers.CharField(required=True)
    email = serializers.EmailField(required=True)

    def validate(self, data):
        name = data[NAME]
        email = data[EMAIL]

        auth_data = super().validate(data)
        auth_data.name = name
        auth_data.email = email

        return self.authenticate(auth_data)


class AccessTokenRefreshSerializer(
    TokenRefreshSerializer,
    BaseAuthenticationSerializer,
):
    def validate(self, data):
        tokens = super().validate(data)

        user_id = self.token_class(tokens[REFRESH]).get(key=api_settings.USER_ID_CLAIM)

        try:
            user = (
                get_users(id=user_id)
                .select_related(
                    "profile_image",
                    "passwordauthentication",
                    "googleauthentication",
                    "facebookauthentication",
                )
                .get()
            )
        except User.DoesNotExist as e:
            logger.warning(e)
            self.raise_invalid_user()

        data = requester_to_json(user)

        return {USER: data, TOKENS: tokens}


class CheckAccountSerializer(BaseAuthenticationSerializer):
    email = serializers.EmailField(required=True)

    def validate(self, data):
        email = data[EMAIL]

        try:
            user = get_users(email=email).get()
            return {EMAIL: user.email, NAME: user.name, IS_ACTIVATED: user.is_activated}
        except User.DoesNotExist as e:
            logger.warning(e)
            pass

        self.raise_invalid_user()


class PasswordResetSerializer(BaseAuthenticationSerializer):
    email = serializers.EmailField(required=True)

    def validate(self, data):
        email = data[EMAIL]

        try:
            user = get_users(email=email).get()
        except User.DoesNotExist as e:
            logger.warning(e)
            self.raise_invalid_user()
            
        host = os.getenv('HOST')
        uid_b64 = urlsafe_base64_encode(str(user.email).encode('utf-8'))
        token = default_token_generator.make_token(user)

        send_password_reset_mail(user.name, user.email, host, uid_b64, token)

        return {'isResetSuccess': True}
    
class PasswordResetConfirmSerializer(BaseAuthenticationSerializer):
    uid = serializers.CharField(required=True)
    token = serializers.CharField(required=True)
    password = serializers.CharField(required=True)
    
    def validate(self, data):
        uid_b64 = data['uid']
        token = data['token']

        email = urlsafe_base64_decode(uid_b64).decode('ascii')

        try:
            user = get_users(email=email).get()
        except User.DoesNotExist as e:
            logger.warning(e)
            self.raise_invalid_user()

        if not default_token_generator.check_token(user, token):
            raise AuthenticationFailed(detail="Invalid reset token.")
            
        new_password = data['password']
        new_password = reset_password(user=user, new_password=new_password)

        if new_password is None:
            raise InternalServerError(
                detail="An error has occurred while resetting the password."
            )
        
        # The confirmation email is best-effort: a delivery failure (SendGrid
        # 4xx/5xx, missing template) must not turn an already-completed password
        # reset into an error response for the user.
        try:
            send_password_reset_confirmation_mail(user.name, user.email)
        except InternalServerError as exc:
            logger.warning(
                "Password reset succeeded for %s but confirmation email failed: %s",
                user.email,
                exc,
            )

        return {'isResetSuccess': True}
