"""
@changelog
| Version | Description                                                                   | Reference                                      |
| v1.0.0  | Initial implementation: SendGrid dynamic-template email dispatch              |                                                |
| v1.1.0  | Fix AttributeError from print(e.message); log real cause; DEV fallback prints email when SENDGRID_API_KEY is unset | REQ: 20260904-password-reset-flow |
/@changelog

@author chuckyang123
"""
import logging
import os

from django.conf import settings
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail

from pigeonhole.common.exceptions import InternalServerError

logger = logging.getLogger("main")


def send_dynamic_template_mail(email, template_id, template_data):
    message = Mail(
        from_email=f'iReflect Admin <{os.getenv("SENDER_EMAIL_ADDRESS")}>',
        to_emails=email)
    message.template_id = template_id
    message.dynamic_template_data = template_data

    # Local development without SendGrid credentials: log the rendered message
    # instead of failing, mirroring the mock pattern used elsewhere (e.g.
    # feedback/logic.py). Password-reset links can then be opened from the
    # console to exercise the full flow end-to-end.
    if settings.DEBUG and not os.getenv("SENDGRID_API_KEY"):
        logger.info(
            "[DEV EMAIL][template=%s] to=%s data=%s", template_id, email, template_data
        )
        return

    try:
        sg = SendGridAPIClient(os.getenv("SENDGRID_API_KEY"))
        sg.send(message)
    except Exception as exc:  # noqa: BLE001 - convert any delivery failure into a client-safe error
        # NOTE: Python 3 exception objects have no `.message` attribute (the old
        # `print(e.message)` raised AttributeError and masked the real cause,
        # e.g. SendGrid 401/403, missing template or network errors).
        logger.warning("Failed to send email to %s: %s", email, exc)
        raise InternalServerError(
            detail="An error has occurred while sending the email."
        ) from exc


def send_password_reset_mail(name, email, host, uid, token):

    template_id = os.getenv('PASSWORD_RESET_EMAIL_TEMPLATE_ID')
    template_data = {
        "name": name,
        "host": host,
        "uid": uid,
        "token": token
    }

    send_dynamic_template_mail(email, template_id, template_data)


def send_password_reset_confirmation_mail(name, email):

    template_id = os.getenv('PASSWORD_RESET_CONFIRMATION_EMAIL_TEMPLATE_ID')
    template_data = {
        "name": name
    }

    send_dynamic_template_mail(email, template_id, template_data)
