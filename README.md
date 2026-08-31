# War Alert Script

This script monitors RSS feeds for specific news alerts, processes them with OpenAI's API, and sends notifications via Pushover or Telegram. It ensures that duplicate news items are ignored and provides detailed logging for each step of the process.

## Features

- Fetches and parses RSS feeds.
- Monitors FAA NMS NOTAMs for Polish airspace restrictions.
- Detects duplicate news items using MD5 hashes.
- Processes news items using OpenAI's API with custom prompts.
- Sends notifications via Pushover for relevant alerts.
- Handles graceful shutdown via signal handling.
- Configurable via environment variables.

## Requirements

- Python 3.6+
- Required Python libraries:
  - `dotenv`
  - `requests`
  - `openai`
- External APIs:
  - OpenAI API
  - Pushover API

## Installation

1. Clone this repository:
   ```bash
   git clone <repository-url>
   cd <repository-name>
   ```

2. Create a `.env` file in the project root with the following variables:
   ```env
   EMAIL_FROM=<your-email-address>
   EMAIL_TO=<space-separated-list-of-email-addresses>
   RSS_URLS=<space-separated-list-of-rss-urls>
   PUSHOVER_TOKEN=<your-pushover-api-token>
   PUSHOVER_USER=<your-pushover-user-key>
   OPENAI_API_KEY=<your-openai-api-key>
   PROMPT_FILE=<path-to-prompt-file>
   SLEEP_DELAY=600
   SMTP_SERVER=<your-smtp-server>
   SMTP_PORT=<your-smtp-port>
   SMTP_LOGIN=<your-smtp-username>
   SMTP_PASSWORD=<your-smtp-password>
   TELEGRAM_BOT_TOKEN=<your-telegram-bot-token>
   TELEGRAM_CHANNEL_ID=<your-telegram-channel-id>
   TMPDIR=/tmp
   FAA_NMS_CLIENT_ID=<your-faa-nms-client-id>
   FAA_NMS_CLIENT_SECRET=<your-faa-nms-client-secret>
   NOTAM_LOCATIONS="EPWW EPWA"
   NOTAM_QCODES="QATLC,QRTCA,QRTCL,QRRCA"
   NOTAM_PASSTHROUGH_QCODES=QATLC
   NOTAM_CLASSIFICATION=INTERNATIONAL
   HEALTH_PORT=8080
   WEBHOOK_PORT=8080
   WEBHOOK_SECRET=<your-webhook-secret>
   ```
   Adjust `SLEEP_DELAY` (in seconds) and `TMPDIR` as needed.
   Set `HEALTH_PORT` to expose a health check endpoint (`GET /health`).
   Set `WEBHOOK_PORT` and `WEBHOOK_SECRET` to enable inbound webhooks.
   Set `FAA_NMS_CLIENT_ID` and `FAA_NMS_CLIENT_SECRET` to enable NOTAM monitoring via the FAA NMS API (request access at notams@faa.gov). Use `NOTAM_LOCATIONS` (space-separated ICAO codes, default `EPWW EPWA`) and `NOTAM_QCODES` (comma-separated Q-code prefixes) to filter airspace closure notices. `NOTAM_PASSTHROUGH_QCODES` (default `QATLC`) always passes through without text filtering — use this for TMA/CTR closures. Routine TRA/PJE/UAV/AUP noise is filtered via `NOTAM_TEXT_EXCLUDE` (comma-separated substrings; see `.env.example` for defaults). Set either variable to empty to disable that stage. Optionally set `NOTAM_CLASSIFICATION` (`INTERNATIONAL`, `DOMESTIC`, `MILITARY`, `LOCAL_MILITARY`, `FDC`) to narrow API results; leave unset or empty to fetch all active NOTAMs for each location. For staging, override `FAA_NMS_BASE_URL` and `FAA_NMS_AUTH_URL` (see `.env.example`).

3. Modify the `prompt.txt` file with your OpenAI query template.

## Usage

Run the script using:
```bash
./war-alert.sh
```

### Logging
The script logs to `stdout` with detailed information about each step, including any errors encountered during API calls or processing.

### Notifications
Relevant alerts are sent as Pushover notifications with the title "War Alert" and the justification from the OpenAI response.

### NOTAM monitoring
When FAA NMS credentials are configured, the script polls active NOTAMs for the locations in `NOTAM_LOCATIONS` and notifies on matches for `NOTAM_QCODES` (airspace closures and restrictions). A two-stage noise filter reduces routine operational NOTAMs: `NOTAM_PASSTHROUGH_QCODES` (default `QATLC`) always alerts — this covers TMA/CTR closures such as the Warsaw incident in September 2025; other matched Q-codes are dropped when their text contains any substring from `NOTAM_TEXT_EXCLUDE` (default: PJE, paragliding, UAV, AUP, AIP SUP, area manager, state aviation, temporary reserved/restricted). Notifications are deduplicated via `ProcessorUnique`; standing restrictions such as EPR129/EP130 are reported once on first sight. By default no `classification` filter is sent to the API (broader results); set `NOTAM_CLASSIFICATION=INTERNATIONAL` to restore the narrower scope. Staging endpoints: `FAA_NMS_BASE_URL=https://api-staging.cgifederal-aim.com/nmsapi` and `FAA_NMS_AUTH_URL=https://api-staging.cgifederal-aim.com/v1/auth/token`. The FAA staging API enforces ~1 request/s per client; use `NOTAM_REQUEST_DELAY` (default `1.1`) to pace location queries. On first run many NOTAMs may match at once; Telegram notifications are throttled via `TELEGRAM_MIN_INTERVAL` (default `1.0` s) with automatic retry on HTTP 429. Items are marked as seen after they are processed (including when a downstream processor such as OpenAI rejects them) or after at least one notifier succeeds; only failed deliveries are retried on the next poll cycle.

Each NOTAM poll cycle logs `info` lines to confirm connectivity and data: `FAA NMS token acquired` or `FAA NMS token reused` (with `auth_url`, so you can verify staging vs production), `FAA NMS NOTAMs fetched` per location (with `base_url`, `count`, and parsed `notams`: number, location, qcode), `NOTAM filtered as noise` for dropped routine items, and `NOTAM fetch complete` with total `fetched`, `filtered`, and `matched` counts.

## Webhooks

When `HEALTH_PORT` or `WEBHOOK_PORT` is set, the script starts an HTTP server alongside the polling loop. The `/health` endpoint is always available without authentication. Webhook endpoints require both `WEBHOOK_PORT` and `WEBHOOK_SECRET`.

### Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Health check, returns `{"status": "ok"}` |
| `POST` | `/webhook/alert` | Immediate notification (no AI filtering) |
| `POST` | `/webhook/news` | AI-filtered notification (same as RSS) |

All webhook endpoints require the header `Authorization: Bearer <WEBHOOK_SECRET>`.

### Payload

```json
{
  "title": "Required — alert or article title",
  "description": "Optional — body text",
  "pubDate": "Optional — defaults to current time",
  "link": "Optional — defaults to empty string"
}
```

### Examples

```bash
# Immediate alert
curl -X POST http://localhost:8080/webhook/alert \
  -H "Authorization: Bearer your-secret-token-here" \
  -H "Content-Type: application/json" \
  -d '{"title": "Air raid alert", "description": "Lviv", "link": "https://example.com"}'

# News for AI processing
curl -X POST http://localhost:8080/webhook/news \
  -H "Authorization: Bearer your-secret-token-here" \
  -H "Content-Type: application/json" \
  -d '{"title": "NATO statement on...", "description": "Full text...", "link": "https://example.com/article"}'
```

### Responses

| Code | Body | Meaning |
|------|------|---------|
| `200` | `{"status": "notified"}` | Notification sent |
| `200` | `{"status": "ignored"}` | Duplicate or rejected by AI |
| `400` | `{"error": "..."}` | Invalid JSON or missing title |
| `401` | `{"error": "Unauthorized"}` | Missing or invalid Bearer token |
| `404` | `{"error": "Not found"}` | Unknown path |

## Notes

- Ensure the OpenAI and Pushover credentials are valid.
- Adjust RSS feed URLs and prompt content to match your requirements.
- Temporary files for tracking processed items are stored in the directory specified by the `TMPDIR` environment variable.

## License

This project is licensed under the MIT License. See the `LICENSE` file for details.

## Contributing

Feel free to open issues or submit pull requests to improve this script.
