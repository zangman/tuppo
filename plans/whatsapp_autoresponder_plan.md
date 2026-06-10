# 🤖 WhatsApp Autoresponder Implementation Plan (Updated)

This document outlines the architecture, guardrails, and implementation steps for adding an intelligent, self-updating autoresponder to the WhatsApp ingestion system.

## 🎯 Goal
Implement a system that automatically responds to specific WhatsApp users. The bot should use available context (Calendar, Chat History, Owner Profile) to provide helpful answers, and fall back to a polite "unavailable" message if it lacks the necessary information.

---

## 🛠️ Refined Architectural Overview
The system consists of the Node.js WhatsApp client, an active Python Response Agent, and a shared Session-based Core Brain.

**The Webhook Flow (Push Model)**: 
`WhatsApp Message` $\rightarrow$ `Node.js Server` $\rightarrow$ `HTTP POST /webhook` $\rightarrow$ `Python Response Agent` $\rightarrow$ `Core Brain (Session-isolated LLM/Tools)` $\rightarrow$ `Node.js Server (POST /send-message)` $\rightarrow$ `WhatsApp Response`.

This push-based model eliminates SQLite polling, avoiding database locks and ensuring near-instantaneous responses.

---

## 📋 Core Components & New Features

### 1. 🧠 The Shared Brain & Session Isolation (`core_brain.py`)
To prevent conversation histories from bleeding into each other (even if you are the only administrator):
- **Session Keys**: Conversation histories will be strictly isolated using unique keys:
  - `tg_admin` (Your direct control channel on Telegram).
  - `wa_{sender_id}` (Unique sessions for each WhatsApp contact).
- **Consolidated Tools**: Both the Telegram bot and the WhatsApp agent will import `core_brain.py` to route LLM calls and calendar/search tools.

### 2. 📝 Dynamic Briefing & Status Updates
To allow the bot to answer personal questions (e.g., *"Where are you?"* or *"When are you back?"*):
- **Profile Store (`owner_profile.json`)**: A flat JSON file containing key-value pairs representing your current status (e.g., `current_location`, `availability`, `current_focus`).
- **Dynamic Tool (`update_owner_status`)**: A new tool registered to the LLM. 
  - **Usage**: You can text your Telegram bot: *"I am traveling in Tokyo until June 5th."* 
  - **Action**: The LLM will call `update_owner_status(key="current_location", value="Tokyo (until June 5th)")`, immediately saving it. The WhatsApp agent will use this context for future responses.

### 3. 🧪 Self-Testing Mode & The "Safety Fuse"
To allow safe testing of the autoresponder without creating infinite loops:
- **Configuration (`autoresponder_config.json`)**:
  ```json
  {
    "test_mode": true,
    "allowed_targets": ["1234567890@c.us"],
    "response_delay_seconds_min": 5,
    "response_delay_seconds_max": 15
  }
  ```
- **Self-Test Bypass**: When `test_mode` is enabled, the bot will allow responses to your own phone number's chat (the "Me" chat).
- **The Safety Fuse**: A strict loop-detection algorithm:
  - If the bot detects more than 3 consecutive responses to the same chat in under 60 seconds, it will automatically disable the autoresponder for that chat and alert you on Telegram: *"⚠️ Autoresponder loop detected! Safety shutoff triggered."*
  - Explicitly ignores all other outgoing messages (`fromMe: true`) to prevent AI-to-AI chat feedback loops.

### 4. 🏷️ Node.js Gateway Filter (`whatsapp_server`)
- **Group Filtering**: Group chats end in `@g.us` in `whatsapp-web.js`. The Node.js server will strictly drop any incoming group messages before sending them to the Python webhook, ensuring the autoresponder never replies in a group.
- **Recipient Check**: Only forwards messages to the Python webhook if the sender is listed in `allowed_targets` or if `test_mode` is active for your own number.

---

## 📋 Step-by-Step Implementation Roadmap

1.  **Step 1: Node.js Upgrades**
    - Implement `POST /send-message` to allow sending WhatsApp messages from Python.
    - Implement incoming message checking: Filter out groups (`@g.us`), check target list, and `POST` valid messages to Python's `/webhook`.
2.  **Step 2: Core Brain Extraction**
    - Refactor `bot.py` tool execution and LLM communication into `core_brain.py`.
    - Implement multi-session memory tracking.
3.  **Step 3: Dynamic Profile and Update Tool**
    - Create `owner_profile.json`.
    - Create the `update_owner_status` tool in `tools/` and register it in `core_brain.py`.
4.  **Step 4: Python Webhook Server (`whatsapp_agent.py`)**
    - Build a lightweight webhook receiver (using FastAPI or Flask) to receive pushed WhatsApp messages.
    - Implement the "Safety Fuse" loop-prevention and timing delays.
    - Inject the `owner_profile.json` as system prompt context before passing the message to the LLM.
