# komodo-mailer

Email alerts for [Komodo](https://komo.do). A small container that receives alerts from a Komodo **Custom** alerter and sends them as HTML email through any SMTP relay. It uses only the Python standard library.

## Features

- HTML email with a colour-coded status banner and a table of the key details, plus a plain-text fallback.
- Friendly titles for Komodo alert types, such as `[CRITICAL] Server unreachable: server-1`.
- Resolved alerts are skipped by default.
- A shared token protects the endpoint.

## Quick start

1. Create your environment file and fill it in:

   ```bash
   cp .env.example .env
   ```

2. Start the container on the same Docker network as Komodo Core:

   ```bash
   docker compose up -d --build
   ```

3. In Komodo, go to **Alerters > New**, choose the **Custom** endpoint, and set the URL to:

   ```text
   http://komodo-mailer:8080/?token=<AUTH_TOKEN>
   ```

4. Click **Test Alerter** and check that the email arrives.

If you deploy the SMTP alerter as a Komodo Stack, turn on **Run Build** in the Stack config, otherwise redeploys will keep using the old image.

## Configuration

| Variable | Required | Default | Description |
| --- | --- | --- | --- |
| `SMTP_HOST` | No | `mail.smtp2go.com` | SMTP relay hostname |
| `SMTP_PORT` | No | `587` | 465 uses implicit TLS, any other port uses STARTTLS |
| `SMTP_USER` | Yes | | SMTP username |
| `SMTP_PASS` | Yes | | SMTP password. In `.env`, write any `$` as `$$` |
| `MAIL_FROM` | Yes | | Sender address. It must be allowed to send through your relay |
| `MAIL_TO` | Yes | | Comma-separated recipients |
| `AUTH_TOKEN` | Yes | | Shared secret Komodo passes as `?token=`. Generate one with `openssl rand -hex 32` |
| `SEND_RESOLVED` | No | `false` | Also email when an alert clears (doesn't affect test notifications) |
| `LOG_LEVEL` | No | `INFO` | `DEBUG` also logs the raw JSON of every alert |
| `KOMODO_NETWORK` | No | `komodo_default` | Docker network that Komodo Core is attached to |

## Responses

| Status | Meaning |
| --- | --- |
| 200 | Email sent, resolved alert skipped, or GET health check |
| 400 | Body missing, not JSON, or not a JSON object |
| 401 | Token missing or wrong |
| 413 | Body larger than 1 MiB |
| 502 | SMTP relay unreachable or rejected the message (see the container logs) |

Failed sends are not queued or retried.

## Security

- Only containers on the Komodo network can reach the service.
- Every alert value is HTML-escaped before it is put into the email.
- The container runs as `nobody`. `.env` is excluded from Git and from the Docker build context.
