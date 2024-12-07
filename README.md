# War Alert Script

This script monitors RSS feeds for specific news alerts, processes them with OpenAI's API, and sends notifications via Pushover or Telegram. It ensures that duplicate news items are ignored and provides detailed logging for each step of the process.

## Features

- Fetches and parses RSS feeds.
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
   RSS_URLS=<space-separated-list-of-rss-urls>
   PUSHOVER_TOKEN=<your-pushover-api-token>
   PUSHOVER_USER=<your-pushover-user-key>
   OPENAI_API_KEY=<your-openai-api-key>
   PROMPT_FILE=<path-to-prompt-file>
   SLEEP_DELAY=600
   TELEGRAM_BOT_TOKEN=<your-telegram-bot-token>
   TELEGRAM_CHANNEL_ID=<your-telegram-channel-id>
   TMPDIR=/tmp
   ```
   Adjust `SLEEP_DELAY` (in seconds) and `TMPDIR` as needed.

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

## Notes

- Ensure the OpenAI and Pushover credentials are valid.
- Adjust RSS feed URLs and prompt content to match your requirements.
- Temporary files for tracking processed items are stored in the directory specified by the `TMPDIR` environment variable.

## License

This project is licensed under the MIT License. See the `LICENSE` file for details.

## Contributing

Feel free to open issues or submit pull requests to improve this script.
