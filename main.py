"""Entry point for komodo-mailer: a tiny HTTP receiver for Komodo Custom alerters.

Accepts POSTed Komodo alert JSON on any path, checks a shared token passed as the
``token`` query parameter, and relays each alert as an email via SMTP. GET returns
a plain "ok" for container health checks.
"""

import argparse
import hmac
import json
import logging
import os
import smtplib
from functools import partial
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from alert_format import format_alert
from config import Settings, load_settings
from email_sender import send_email

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_BIND = "0.0.0.0"
DEFAULT_PORT = 8080
MAX_BODY_BYTES = 1024 * 1024
TOKEN_PARAM = "token"
LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"
DEFAULT_LOG_LEVEL = "INFO"
# Komodo sends "Test Alerter" alerts already marked resolved, so they bypass the resolved filter.
TEST_ALERT_TYPE = "Test"

log = logging.getLogger("komodo_mailer")


# ---------------------------------------------------------------------------
# Filtering
# ---------------------------------------------------------------------------


def should_send(alert: dict[str, object], settings: Settings) -> bool:
    """Decide whether an alert should be emailed.

    Args:
        alert: The decoded Komodo alert.
        settings: Delivery settings.

    Returns:
        False for resolved alerts when SEND_RESOLVED is off (except test alerts), otherwise True.
    """
    if settings.send_resolved or not alert.get("resolved"):
        return True
    data = alert.get("data")
    return isinstance(data, dict) and data.get("type") == TEST_ALERT_TYPE


# ---------------------------------------------------------------------------
# HTTP handler
# ---------------------------------------------------------------------------


class AlertHandler(BaseHTTPRequestHandler):
    """Handle Komodo alert POSTs and health-check GETs."""

    def __init__(self, *args: object, settings: Settings, **kwargs: object) -> None:
        """Store settings, then let the base class process the request.

        Args:
            *args: Positional arguments for BaseHTTPRequestHandler.
            settings: SMTP and auth settings.
            **kwargs: Keyword arguments for BaseHTTPRequestHandler.
        """
        self.settings = settings
        super().__init__(*args, **kwargs)

    def do_GET(self) -> None:
        """Respond to health checks."""
        self._respond(HTTPStatus.OK, b"ok")

    def do_POST(self) -> None:
        """Validate, format and email a Komodo alert."""
        if not self._token_valid():
            log.warning("Rejected request with missing or invalid token from %s", self.client_address[0])
            self._respond(HTTPStatus.UNAUTHORIZED)
            return

        alert = self._read_alert()
        if alert is None:
            return

        # The raw payload is not in the email, so make it available for troubleshooting.
        log.debug("Received alert: %s", json.dumps(alert))
        email = format_alert(alert)
        if not should_send(alert, self.settings):
            log.info("Skipped resolved alert: %s", email.subject)
            # 200 so Komodo does not record the alerter as failing.
            self._respond(HTTPStatus.OK)
            return

        try:
            send_email(self.settings, email.subject, email.text, email.html)
        except (smtplib.SMTPException, OSError):
            log.exception("Failed to send alert email: %s", email.subject)
            self._respond(HTTPStatus.BAD_GATEWAY)
            return

        log.info("Sent alert email: %s", email.subject)
        self._respond(HTTPStatus.OK)

    def _token_valid(self) -> bool:
        """Check the request's token query parameter against the configured secret.

        Returns:
            True if the token matches.
        """
        supplied = parse_qs(urlparse(self.path).query).get(TOKEN_PARAM, [""])[0]
        # Constant-time comparison to avoid leaking the token through timing.
        return hmac.compare_digest(supplied.encode(), self.settings.auth_token.encode())

    def _read_alert(self) -> dict[str, object] | None:
        """Read and decode the request body, responding with an error if it is invalid.

        Returns:
            The decoded alert, or None if an error response has already been sent.
        """
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self._respond(HTTPStatus.BAD_REQUEST)
            return None
        if length <= 0 or length > MAX_BODY_BYTES:
            log.warning("Rejected body of %d bytes", length)
            self._respond(HTTPStatus.REQUEST_ENTITY_TOO_LARGE if length > 0 else HTTPStatus.BAD_REQUEST)
            return None

        try:
            alert = json.loads(self.rfile.read(length))
        except (json.JSONDecodeError, UnicodeDecodeError):
            log.warning("Rejected non-JSON body")
            self._respond(HTTPStatus.BAD_REQUEST)
            return None
        if not isinstance(alert, dict):
            log.warning("Rejected JSON body that is not an object")
            self._respond(HTTPStatus.BAD_REQUEST)
            return None
        return alert

    def _respond(self, status: HTTPStatus, body: bytes = b"") -> None:
        """Send a response with an optional plain-text body.

        Args:
            status: HTTP status to return.
            body: Response body.
        """
        self.send_response(status)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002 - base class signature
        """Suppress default access logging, which would write the token from the URL to stderr."""


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments.

    Returns:
        The parsed arguments.
    """
    parser = argparse.ArgumentParser(description="Relay Komodo alerts to email via SMTP.")
    parser.add_argument("--bind", default=DEFAULT_BIND, help=f"Address to listen on (default {DEFAULT_BIND})")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"Port to listen on (default {DEFAULT_PORT})")
    return parser.parse_args()


def main() -> None:
    """Load settings and serve until interrupted."""
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", DEFAULT_LOG_LEVEL).upper(), format=LOG_FORMAT)
    args = parse_args()
    settings = load_settings()

    server = ThreadingHTTPServer((args.bind, args.port), partial(AlertHandler, settings=settings))
    log.info("Listening on %s:%d with %r", args.bind, args.port, settings)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log.info("Shutting down")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
