# War Alert

Monitors RSS feeds, Twitter/X accounts, Telegram channels, and FAA NOTAMs.
Relevant items are filtered with a configurable LLM and sent through Pushover,
ntfy, Telegram, or email.

## Quick start

```bash
git clone <repository-url>
cd war-alert
cp .env.example .env
# Edit .env — enable only the sources and notifiers you need
docker compose up -d
```

Without Docker:

```bash
cp .env.example .env
# Edit .env and prompt.txt
./war-alert.sh
```

All configuration is via environment variables. See `.env.example` for the
full list with defaults and comments.

## What it monitors

| Source | Enable with |
|--------|-------------|
| RSS feeds | `RSS_URLS` |
| Twitter/X | `TWITTERAPI_KEY`, `TWITTERAPI_USERNAMES` |
| Telegram channels | `TELEGRAM_API_ID`, `TELEGRAM_API_HASH`, `telegram.yaml` |
| FAA NOTAMs (Polish airspace) | `FAA_NMS_CLIENT_ID`, `FAA_NMS_CLIENT_SECRET` |
| Alerts.in.ua | `ALERTSUA_TOKEN` |

RSS, Twitter, and Telegram posts go through LLM classification
(`CLASSIFICATION_PROCESSOR`, `PROMPT_FILE`). NOTAMs and webhook alerts skip
the classifier.

## Notifications

Configure any combination:

| Notifier | Enable with |
|----------|-------------|
| Pushover | `PUSHOVER_TOKEN`, `PUSHOVER_USER` |
| ntfy | `NTFY_TOPIC` |
| Telegram (bot) | `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHANNEL_ID` |
| Email | `EMAIL_FROM`, `EMAIL_TO`, SMTP settings |

The notification bot (`TELEGRAM_BOT_TOKEN`) is separate from Telegram channel
monitoring (Telethon user account).

## Telegram channel monitoring

1. Get `TELEGRAM_API_ID` and `TELEGRAM_API_HASH` from
   [my.telegram.org](https://my.telegram.org).
2. Edit `telegram.yaml` — list channels and optional regex filters.
3. Log in once (stop war-alert first):

   ```bash
   docker compose stop war-alert
   docker compose run --rm -it war-alert python3 telegram_login.py
   docker compose up -d
   ```

   Set `TELEGRAM_PHONE=+48...` in `.env` to skip the phone prompt.

**Session problems:** if logs show `Server sent a very old message` or
`Security error`, stop war-alert, delete `telegram.session` and
`telegram.session-journal`, then log in again.

## Docker

The HTTP server listens on port `8080` inside the container. On the host it is
bound to `127.0.0.1` (override with `WEBHOOK_PORT` in `.env`).

### Reverse proxy (nginx)

To attach the container to an existing Docker network:

```env
DOCKER_NETWORK=existing-network
DOCKER_NETWORK_EXTERNAL=true
```

Then point nginx at the container by name:

```nginx
resolver 127.0.0.11 valid=30s;
set $upstream_war_alert war-alert;
proxy_pass http://$upstream_war_alert:8080;
```

## Webhooks

When `HEALTH_PORT` or `WEBHOOK_PORT` is set, an HTTP server runs alongside
the polling loop.

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `GET` | `/health` | none | Returns `{"status": "ok"}` |
| `POST` | `/webhook/alert` | Bearer | Immediate notification (no AI) |
| `POST` | `/webhook/news` | Bearer | AI-filtered (same as RSS) |

Webhook routes require `WEBHOOK_SECRET` and the header
`Authorization: Bearer <WEBHOOK_SECRET>`.

**Payload:**

```json
{
  "title": "Required",
  "description": "Optional body text",
  "pubDate": "Optional — defaults to now",
  "link": "Optional URL"
}
```

**Examples:**

```bash
curl -X POST http://localhost:8080/webhook/alert \
  -H "Authorization: Bearer your-secret-token-here" \
  -H "Content-Type: application/json" \
  -d '{"title": "Air raid alert", "description": "Lviv"}'

curl -X POST http://localhost:8080/webhook/news \
  -H "Authorization: Bearer your-secret-token-here" \
  -H "Content-Type: application/json" \
  -d '{"title": "NATO statement", "description": "Full text..."}'
```

**Responses:**

| Code | Body | Meaning |
|------|------|---------|
| `200` | `{"status": "notified"}` | Notification sent |
| `200` | `{"status": "ignored"}` | Duplicate or rejected by AI |
| `400` | `{"error": "..."}` | Invalid JSON or missing title |
| `401` | `{"error": "Unauthorized"}` | Missing or invalid token |
| `404` | `{"error": "Not found"}` | Unknown path |

## Logging

The script logs JSON lines to stdout. Set `LOG_LEVEL` to `DEBUG`, `INFO`
(default), `WARNING`, or `ERROR`.

Send `SIGUSR1` to trigger a test notification.

## Requirements

- Python 3.6+
- Dependencies: `dotenv`, `requests`, `openai`, `telethon`, `PyYAML`

## License

MIT — see `LICENSE`.

## Contributing

Issues and pull requests are welcome.
