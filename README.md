# Tuppo - Personal Coordinator

An AI personal assistant that runs on a local LLM (llama.cpp) and integrates with **Telegram** for conversation and **WhatsApp** for autoresponding, messaging, and group monitoring.

> **Disclaimer:** This project was built for personal, solo use only. It is not intended for production or third-party use. No support, guarantees, or maintenance will be provided. Use at your own risk.

> **Coding history:** Vibe-coded with Qwen3.6-27B and Gemma4-31B, with occasional input from Gemini 3.5 Flash (< 10 times).

## Table of Contents

- [Features](#features)
  - [Telegram Interface](#telegram-interface)
  - [WhatsApp Autoresponder](#whatsapp-autoresponder)
  - [Scheduling & Automation](#scheduling--automation)
  - [Tools](#tools)
- [Architecture](#architecture)
- [Setup](#setup)
- [Database](#database)
- [Limitations](#limitations)
- [Tools Used](#tools-used)
- [Extendability](#extendability)
- [Notes](#notes)

## Features

### Telegram Interface
- Chat with a local LLM via Telegram messages
- Markdown-formatted responses, long-message chunking
- **Human-in-the-loop WhatsApp messaging** - propose messages and approve/cancel via inline buttons
- **Scheduling** - set one-time or recurring reminders, WhatsApp messages, group summaries, and dynamic LLM tasks
- **Google Calendar** - list, create, update, and delete events across personal + home calendars
- **Owner profile** - view and update current status (location, availability, focus)
- **WhatsApp contact lookup** - resolve names to chat IDs
- **Pending messages** - view messages that WhatsApp contacts left for you via the autoresponder

#### Commands
| Command | Description |
|---------|-------------|
| `/start` | Start the bot |
| `/health` | Show GPU/CPU stats |
| `/clear_context` | Clear the conversation memory |
| `/tps` | Toggle performance metrics in responses |
| `/wa_on` / `/wa_off` | Enable/disable WhatsApp autoresponder |
| `/wa_list` | List all WhatsApp contacts |
| `/wa_list groups` | List WhatsApp groups only |
| `/wa_list private` | List private chats only |
| `/wa_groups` | Show groups allowed for autoresponse |
| `/wa_group_add <name>` | Add a group to the autoresponder allowlist |
| `/wa_group_remove <name>` | Remove a group from the allowlist |

### WhatsApp Autoresponder

> **Experimental.** Making a useful autoresponder is hard. If it's too empowered, it's dangerous. If it isn't, it's useless. So where's the sweet spot? This sort of works, but it's gimmicky at best.

- Responds automatically in **private chats** (allowed contacts only) and **group chats** (when @mentioned or replied to)
- Casual, human-like tone with rate limiting and loop prevention
- **Context-aware** - reads recent conversation history before responding
- **Calendar lookups** - checks availability when asked
- **"Take a message"** - saves messages for the owner when someone asks the bot to pass along info
- All bot responses prefixed with `🤖` so recipients know it's not the owner

### Scheduling & Automation
| Action | Description |
|--------|-------------|
| Telegram reminders | Send a message to Telegram at a set time |
| WhatsApp messages | Send messages to WhatsApp contacts/groups on a schedule |
| WhatsApp summaries | Periodic group chat summaries delivered to Telegram |
| Dynamic LLM tasks | Run any LLM prompt on a schedule (e.g., daily news briefing) |

Supports one-time (`execution_time`) or recurring (`cron_expression`) tasks. All tasks are persisted in SQLite and survive restarts.

### Tools
- **Web search** - local SearXNG instance for reliable search
- **Page fetching** - retrieve full text content from URLs
- **Calculator** - mathematical operations
- **Owner profile** - read/write personal status
- **Google Calendar** - full CRUD with timezone handling

## Architecture

```
┌───────────┐
│ Telegram  │  polling
└─────┬─────┘
      │
      ▼
┌───────────┐     ┌──────────────┐
│  bot.py   │────▶│  llama.cpp   │
│ (main bot)│     │ (local LLM)  │
└─────┬─────┘     └──────────────┘
      │
      │  core_brain.py
      │  (session mgmt, tools, RBAC)
      │
      ▼
┌───────────────┐
│  config.yaml  │
│  (settings)   │
└───────────────┘


┌───────────┐
│ WhatsApp  │
└─────┬─────┘
      │
      ▼
┌──────────────────┐
│ Node.js Gateway  │  port 3000
│ (whatsapp-web.js)│
└─────┬────────────┘
      │  /webhook
      ▼
┌──────────────────┐
│ whatsapp_agent   │  FastAPI, port 5000
└──────────────────┘
```

**WhatsApp message flow:** WhatsApp → Node.js gateway → SQLite DB → FastAPI webhook (`whatsapp_agent.py`) → LLM → response sent back via gateway.

**Telegram message flow:** Telegram → `bot.py` → `core_brain.py` (LLM + tool calls) → response back to Telegram.

Both paths share the same `core_brain.py` for LLM communication, session management, and tool execution.

## Setup

### Prerequisites
- Python 3.14 (or compatible)
- llama.cpp server running with OpenAI-compatible API
- Node.js (for WhatsApp gateway)
- Telegram bot token (from [@BotFather](https://t.me/BotFather))
- Google OAuth credentials (`credentials.json`) for calendar access
- SearXNG instance (optional, for web search) — [Docker install guide](https://docs.searxng.org/admin/installation-docker.html)

### 1. Install Python Dependencies
```bash
cd telegram_bot
python -m venv v
source v/bin/activate
pip install -r requirements.txt
```

### 2. Configure
Copy the example config and fill in your own values:

```bash
cp config_example.yaml config.yaml
```

Then edit `config.yaml` - every field is documented with comments explaining what it does and how to obtain the value.

### 3. Set Telegram Token
Save your bot token (from BotFather) to the `token` file:
```bash
echo "YOUR_BOT_TOKEN_HERE" > token
```

### 4. Register Bot Commands (Optional)
For Telegram to show a command menu, register them with BotFather:
1. Open [@BotFather](https://t.me/BotFather)
2. Send `/setcommands` for your bot
3. Paste:
```
start - Start the bot
health - Show GPU/CPU stats
clear_context - Clear conversation memory
tps - Toggle performance metrics
wa_on - Enable WhatsApp autoresponder
wa_off - Disable WhatsApp autoresponder
wa_list - List WhatsApp contacts
wa_groups - Show allowed groups
wa_group_add - Add group to autoresponder
wa_group_remove - Remove group from autoresponder
```

### 5. Set Up Google Calendar (Optional)
Run the OAuth setup to generate `token.json`:
```bash
python setup_auth.py
```

### 6. Set Up WhatsApp Gateway (Optional)
```bash
cd whatsapp_server
npm install
npm start
```
This starts the WhatsApp Web gateway on port 3000. Scan the QR code to connect.

### 7. Install SearXNG (Optional)

SearXNG provides web search results for the bot. If you don't install it, the web search tool will fail with a connection error.

Quick install with Docker:

```bash
docker run -d --name searxng -p 8081:8080 \
  -e SEARXNG_BASE_URL=http://localhost:8081/ \
  searxng/searxng:latest
```

Then set `searxng.url` to `http://localhost:8081/search` in your `config.yaml`.

Full setup guide: [SearXNG Docker Installation](https://docs.searxng.org/admin/installation-docker.html)

### 8. Start the Bot

**Start the WhatsApp agent (if using WhatsApp):**
```bash
python whatsapp_agent.py
```
This runs the FastAPI webhook on port 5000.

**Start the Telegram bot:**
```bash
python bot.py
```

## Database

All persistent data is stored in `whatsapp.db` (SQLite):

| Table | Purpose |
|-------|---------|
| `whatsapp_messages` | All received WhatsApp messages |
| `contacts` | Auto-populated contact/group directory |
| `chat_status` | Last-read bookmarks per chat |
| `scheduled_tasks` | Pending and completed scheduled tasks |
| `whatsapp_proposals` | Messages awaiting owner approval |
| `event_proposals` | Calendar events awaiting owner approval |
| `messages_for_owner` | Messages that contacts asked the bot to pass along |

## Limitations

- **Single user only** - the Telegram bot is designed for one owner. There is no multi-user support or user isolation beyond the owner's chat ID.
- **Single WhatsApp account** - only one WhatsApp Web session can be linked at a time via `whatsapp-web.js`.
- **In-memory sessions** - conversation context is held in process memory and is lost on restart. Only scheduled tasks and DB records persist.
- **Local LLM required** - the bot connects to a local llama.cpp server only. No cloud LLM providers (OpenAI, Anthropic, etc.) are supported.
- **No webhook authentication** - the WhatsApp webhook endpoint (`whatsapp_agent.py` port 5000) has no auth. Keep it behind a firewall or reverse proxy if exposed.
- **Plaintext secrets** - Telegram bot token and other credentials are stored in plaintext files. Do not share the repository.
- **SQLite backend** - fine for single-user use but not designed for high concurrency or large-scale message volumes.
- **No message encryption** - all WhatsApp messages, proposals, and notes are stored unencrypted in `whatsapp.db`.
- **Google Calendar OAuth** — the OAuth token expires periodically. You'll need to run `python setup_auth.py` occasionally to refresh it and keep calendar access working.
- **Two calendars only** — Google Calendar integration supports only your personal (primary) calendar plus one additional "home" calendar. Extra calendars are not supported.

## Tools Used

- **[pi.dev](https://pi.dev/)** — the coding harness used to develop, refactor, and maintain this project
- **llama.cpp** — local LLM inference server
- **python-telegram-bot** — Telegram bot framework
- **whatsapp-web.js** — WhatsApp Web automation via Node.js gateway
- **FastAPI** — webhook server for WhatsApp message handling
- **SearXNG** — self-hosted metasearch engine
- **Google Calendar API** — event management
- **SQLite** — persistent storage

## Extendability

This project is open-sourced as a starting point for others to fork and build on.

- **Want to add your own features?** Fork it and vibe-code whatever you need — scheduling, integrations, new tools, the works. The codebase is intentionally unopinionated about what features you add.

## Notes

- LLM model is detected dynamically on each request - swap models in llama.cpp without restarting the bot
- Reasoning content (`reasoning_content`) is kept for Qwen models and stripped for others (e.g., Gemma)
- Session context is capped at ~32K tokens with a sliding window that evicts oldest exchanges
- `config.yaml` is the single source of truth - changes via Telegram commands (e.g., `/wa_on`) persist back to the file
