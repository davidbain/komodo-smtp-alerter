"""Runtime configuration for komodo-mailer.

Reads SMTP and delivery settings from environment variables into an immutable
Settings object, failing fast with a clear message when anything required is missing.
"""

import os
from dataclasses import dataclass

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_SMTP_HOST = "mail.smtp2go.com"
DEFAULT_SMTP_PORT = 587
REQUIRED_VARS = ("SMTP_USER", "SMTP_PASS", "MAIL_FROM", "MAIL_TO", "AUTH_TOKEN")
TRUE_VALUES = {"1", "true", "yes", "on"}
FALSE_VALUES = {"0", "false", "no", "off", ""}


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Settings:
    """SMTP connection and delivery settings.

    Attributes:
        smtp_host: SMTP relay hostname.
        smtp_port: SMTP relay port. 465 uses implicit TLS, anything else uses STARTTLS.
        smtp_user: SMTP username.
        smtp_pass: SMTP password.
        mail_from: Sender address.
        mail_to: Recipient addresses.
        auth_token: Shared secret Komodo must send as the ``token`` query parameter.
        send_resolved: Whether to email alerts that Komodo reports as resolved.
    """

    smtp_host: str
    smtp_port: int
    smtp_user: str
    smtp_pass: str
    mail_from: str
    mail_to: list[str]
    auth_token: str
    send_resolved: bool

    def __repr__(self) -> str:
        """Return a representation that never exposes secrets."""
        return (
            f"Settings(smtp_host={self.smtp_host!r}, smtp_port={self.smtp_port}, "
            f"recipients={len(self.mail_to)}, send_resolved={self.send_resolved})"
        )


def _parse_bool(name: str) -> bool:
    """Read a boolean environment variable, defaulting to False when unset.

    Args:
        name: Environment variable name.

    Returns:
        The parsed value.

    Raises:
        ValueError: If the value is not a recognised true/false word.
    """
    value = os.environ.get(name, "").strip().lower()
    if value in TRUE_VALUES:
        return True
    if value in FALSE_VALUES:
        return False
    raise ValueError(f"{name} must be true or false, got {value!r}")


def load_settings() -> Settings:
    """Build Settings from environment variables.

    Returns:
        The populated Settings.

    Raises:
        ValueError: If a required variable is missing/empty, SMTP_PORT is not an integer,
            or SEND_RESOLVED is not a recognised boolean.
    """
    missing = [name for name in REQUIRED_VARS if not os.environ.get(name, "").strip()]
    if missing:
        raise ValueError(f"Missing required environment variables: {', '.join(missing)}")

    mail_to = [addr.strip() for addr in os.environ["MAIL_TO"].split(",") if addr.strip()]
    if not mail_to:
        raise ValueError("MAIL_TO must contain at least one address")

    return Settings(
        smtp_host=os.environ.get("SMTP_HOST", DEFAULT_SMTP_HOST),
        smtp_port=int(os.environ.get("SMTP_PORT", DEFAULT_SMTP_PORT)),
        smtp_user=os.environ["SMTP_USER"],
        smtp_pass=os.environ["SMTP_PASS"],
        mail_from=os.environ["MAIL_FROM"],
        mail_to=mail_to,
        auth_token=os.environ["AUTH_TOKEN"],
        send_resolved=_parse_bool("SEND_RESOLVED"),
    )
