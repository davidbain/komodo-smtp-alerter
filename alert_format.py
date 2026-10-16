"""Turn a Komodo alert payload into a human-readable email (subject, plain text and HTML).

Komodo's Custom alerter POSTs an Alert object shaped roughly like
``{ts, level, resolved, resolved_ts, target: {type, id}, data: {type, data: {...}}}``.
Field names vary between alert types and Komodo versions, so formatting is defensive:
known alert types get friendly titles and everything else is humanised generically.
All alert values are HTML-escaped before being placed in the HTML body.
"""

import html
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

UNKNOWN_LABEL = "Unknown"
RESOLVED_LABEL = "RESOLVED"
TIMESTAMP_FORMAT = "%d %b %Y %H:%M:%S UTC"
MS_PER_SECOND = 1000
FLOAT_DECIMALS = 1
LABEL_WIDTH = 12
FOOTER_TEXT = "Sent by komodo-mailer"

# Detail keys checked, in order, for a human-readable resource name.
NAME_KEYS = ("name", "server_name")
# Detail keys already shown in the summary, so not repeated as rows.
SUMMARY_KEYS = {"id", "name"}

# Friendly labels for detail keys. Unknown keys fall back to humanise().
DETAIL_LABELS = {
    "server_name": "Server",
    "percentage": "Usage (%)",
    "used_gb": "Used (GB)",
    "total_gb": "Total (GB)",
}

# Friendly titles for known Komodo alert types. Unknown types fall back to humanise().
ALERT_TITLES = {
    "Test": "Test alert",
    "ServerUnreachable": "Server unreachable",
    "ServerCpu": "High CPU usage",
    "ServerMem": "High memory usage",
    "ServerDisk": "High disk usage",
    "ContainerStateChange": "Container state changed",
    "StackStateChange": "Stack state changed",
    "DeploymentImageUpdateAvailable": "Deployment image update available",
    "DeploymentAutoUpdated": "Deployment auto-updated",
    "StackImageUpdateAvailable": "Stack image update available",
    "StackAutoUpdated": "Stack auto-updated",
    "AwsBuilderTerminationFailed": "AWS builder termination failed",
    "ResourceSyncPendingUpdates": "Resource sync has pending updates",
    "BuildFailed": "Build failed",
    "RepoBuildFailed": "Repo build failed",
    "ProcedureFailed": "Procedure failed",
    "ActionFailed": "Action failed",
    "ScheduleRun": "Scheduled run",
}

# Accent colour per state, used for the HTML banner.
STATE_COLOURS = {
    "CRITICAL": "#c0392b",
    "WARNING": "#d68910",
    "OK": "#1e8449",
    RESOLVED_LABEL: "#1e8449",
}
DEFAULT_COLOUR = "#566573"

# Matches the boundary before an uppercase letter that starts a new word, e.g.
# "ServerCpu" -> "Server|Cpu", "AWSBuilder" -> "AWS|Builder".
CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")

# Inline styles only: many mail clients strip <style> blocks.
HTML_TEMPLATE = """\
<!doctype html>
<html>
<body style="margin:0;padding:16px;background:#f4f6f7;">
<div style="max-width:600px;margin:0 auto;background:#ffffff;border:1px solid #e5e8e8;\
font-family:'Segoe UI',Arial,sans-serif;font-size:14px;color:#1c2833;">
  <div style="border-left:6px solid {colour};padding:14px 18px;">
    <div style="font-size:12px;font-weight:bold;letter-spacing:0.5px;color:{colour};">{state}</div>
    <div style="font-size:18px;font-weight:bold;margin-top:4px;">{headline}</div>
  </div>
  <table cellpadding="0" cellspacing="0" style="border-collapse:collapse;width:100%;">
{rows}
  </table>
  <div style="padding:12px 18px;font-size:12px;color:#909497;">{footer}</div>
</div>
</body>
</html>
"""
HTML_ROW_TEMPLATE = (
    '    <tr><td style="padding:6px 18px;color:#717d7e;white-space:nowrap;width:1%;'
    'border-top:1px solid #f2f3f4;">{label}</td>'
    '<td style="padding:6px 18px 6px 0;border-top:1px solid #f2f3f4;">{value}</td></tr>'
)


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AlertEmail:
    """A rendered alert email.

    Attributes:
        subject: Email subject line.
        text: Plain-text body, for clients that do not render HTML.
        html: HTML body.
    """

    subject: str
    text: str
    html: str


# ---------------------------------------------------------------------------
# Value helpers
# ---------------------------------------------------------------------------


def humanise(identifier: str) -> str:
    """Convert a CamelCase or snake_case identifier into a sentence-case phrase.

    Args:
        identifier: For example ``ServerCpu`` or ``used_gb``.

    Returns:
        For example ``Server cpu`` or ``Used gb``.
    """
    words = CAMEL_BOUNDARY.sub(" ", identifier).replace("_", " ").split()
    if not words:
        return identifier
    return " ".join([words[0].capitalize(), *(w if w.isupper() else w.lower() for w in words[1:])])


def format_timestamp(value: Any) -> str | None:
    """Format a Komodo millisecond epoch timestamp.

    Args:
        value: Milliseconds since the Unix epoch, or anything else.

    Returns:
        The formatted UTC time, or None if the value is not a usable timestamp.
    """
    if not isinstance(value, int | float) or isinstance(value, bool) or value <= 0:
        return None
    try:
        return datetime.fromtimestamp(value / MS_PER_SECOND, tz=UTC).strftime(TIMESTAMP_FORMAT)
    except (OverflowError, OSError, ValueError):
        return None


def format_value(value: Any) -> str:
    """Render a detail value for display.

    Args:
        value: Any JSON value from the alert details.

    Returns:
        A short display string.
    """
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, float):
        return f"{value:.{FLOAT_DECIMALS}f}"
    if isinstance(value, dict | list):
        return json.dumps(value)
    return str(value)


def _resource_name(alert: dict[str, Any], details: dict[str, Any]) -> str:
    """Pick the best available display name for the alerted resource.

    Args:
        alert: The full Komodo alert.
        details: The alert's ``data.data`` payload.

    Returns:
        A resource name, the target id, or an empty string.
    """
    for key in NAME_KEYS:
        if details.get(key):
            return str(details[key])
    target = alert.get("target")
    return str(target.get("id", "")) if isinstance(target, dict) else ""


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _render_text(state: str, headline: str, rows: list[tuple[str, str]]) -> str:
    """Render the plain-text body.

    Args:
        state: Status label, e.g. ``CRITICAL`` or ``RESOLVED``.
        headline: Alert title and resource name.
        rows: Ordered ``(label, value)`` pairs.

    Returns:
        The plain-text body.
    """
    lines = [f"{state}: {headline}", ""]
    lines += [f"{label + ':':<{LABEL_WIDTH}}{value}" for label, value in rows]
    lines += ["", FOOTER_TEXT]
    return "\n".join(lines)


def _render_html(state: str, headline: str, rows: list[tuple[str, str]]) -> str:
    """Render the HTML body, escaping every alert-derived value.

    Args:
        state: Status label, e.g. ``CRITICAL`` or ``RESOLVED``.
        headline: Alert title and resource name.
        rows: Ordered ``(label, value)`` pairs.

    Returns:
        The HTML body.
    """
    row_html = "\n".join(
        HTML_ROW_TEMPLATE.format(label=html.escape(label), value=html.escape(value)) for label, value in rows
    )
    return HTML_TEMPLATE.format(
        colour=STATE_COLOURS.get(state, DEFAULT_COLOUR),
        state=html.escape(state),
        headline=html.escape(headline),
        rows=row_html,
        footer=html.escape(FOOTER_TEXT),
    )


def format_alert(alert: dict[str, Any]) -> AlertEmail:
    """Build the email for a Komodo alert.

    Args:
        alert: The decoded JSON alert from Komodo.

    Returns:
        The rendered subject, plain-text body and HTML body.
    """
    level = str(alert.get("level", UNKNOWN_LABEL)).upper()
    resolved = bool(alert.get("resolved", False))
    data = alert.get("data") if isinstance(alert.get("data"), dict) else {}
    kind = str(data.get("type", UNKNOWN_LABEL))
    details = data.get("data") if isinstance(data.get("data"), dict) else {}
    target = alert.get("target") if isinstance(alert.get("target"), dict) else {}

    title = ALERT_TITLES.get(kind, humanise(kind))
    name = _resource_name(alert, details)
    headline = f"{title}: {name}" if name else title
    state = RESOLVED_LABEL if resolved else level

    rows = [("Status", "Resolved" if resolved else f"Open, {level}")]
    if raised := format_timestamp(alert.get("ts")):
        rows.append(("Raised", raised))
    if resolved and (cleared := format_timestamp(alert.get("resolved_ts"))):
        rows.append(("Resolved", cleared))
    if resource := " ".join(part for part in (str(target.get("type", "")), name) if part):
        rows.append(("Resource", resource))
    rows += [
        (DETAIL_LABELS.get(key, humanise(key)), format_value(value))
        for key, value in details.items()
        if key not in SUMMARY_KEYS and value is not None
    ]

    return AlertEmail(
        subject=f"[{state}] {headline}",
        text=_render_text(state, headline, rows),
        html=_render_html(state, headline, rows),
    )
