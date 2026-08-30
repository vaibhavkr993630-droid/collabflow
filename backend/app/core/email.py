import smtplib
from email.mime.text import MIMEText

from app.core.config import get_settings

settings = get_settings()


def send_email(*, to_email: str, subject: str, body: str) -> None:
    """
    Blocking (smtplib, not async) — deliberately: this is only ever called from a
    Celery task, which already runs on its own worker thread/process outside the
    API's event loop, so there's no event loop to block. In local dev, `smtp_host`
    points at the MailDev container (docker-compose.yml) — no real credentials
    needed, and sent mail is viewable at http://localhost:1080. In production
    this points at a real relay (e.g. Resend's SMTP endpoint) that requires
    STARTTLS + auth — smtp_user/smtp_password being set is what switches this
    into that mode, so the same function works unmodified in both environments.
    """
    message = MIMEText(body)
    message["Subject"] = subject
    message["From"] = settings.smtp_from
    message["To"] = to_email

    with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as smtp:
        if settings.smtp_user and settings.smtp_password:
            smtp.starttls()
            smtp.login(settings.smtp_user, settings.smtp_password)
        smtp.send_message(message)
