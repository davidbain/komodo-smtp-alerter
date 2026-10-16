"""Send multipart (plain text + HTML) email through an authenticated SMTP relay.

Uses implicit TLS on port 465 and STARTTLS on every other port, so credentials
are never sent in clear text.
"""

import smtplib
import ssl
from email.message import EmailMessage

from config import Settings

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

IMPLICIT_TLS_PORT = 465
SMTP_TIMEOUT_SECONDS = 20


# ---------------------------------------------------------------------------
# Sending
# ---------------------------------------------------------------------------


def send_email(settings: Settings, subject: str, text: str, html: str) -> None:
    """Send a multipart (plain text + HTML) email to all configured recipients.

    Args:
        settings: SMTP connection and delivery settings.
        subject: Email subject line.
        text: Plain-text body, shown by clients that do not render HTML.
        html: HTML body.

    Raises:
        smtplib.SMTPException: If the relay rejects TLS, authentication or the message.
        OSError: If the relay cannot be reached or the connection times out.
    """
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = settings.mail_from
    message["To"] = ", ".join(settings.mail_to)
    message.set_content(text)
    message.add_alternative(html, subtype="html")

    tls_context = ssl.create_default_context()
    if settings.smtp_port == IMPLICIT_TLS_PORT:
        smtp = smtplib.SMTP_SSL(
            settings.smtp_host, settings.smtp_port, timeout=SMTP_TIMEOUT_SECONDS, context=tls_context
        )
    else:
        smtp = smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=SMTP_TIMEOUT_SECONDS)

    with smtp:
        if settings.smtp_port != IMPLICIT_TLS_PORT:
            smtp.starttls(context=tls_context)
        smtp.login(settings.smtp_user, settings.smtp_pass)
        smtp.send_message(message)
