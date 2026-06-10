# Plan: Telegram-to-WhatsApp Messaging with Confirmation (Refined)

This document outlines the implementation of a feature allowing the owner to send WhatsApp messages to specific people via the Telegram bot, including approximate name lookup and a safety confirmation loop.

## 1. Objectives
- Allow sending WhatsApp messages via Telegram commands.
- Implement approximate name lookup to resolve contacts without needing exact Chat IDs.
- Implement a "Human-in-the-Loop" confirmation system using Telegram inline buttons directly attached to the bot's reply.

## 2. Technical Architecture

### A. Database Schema (`whatsapp.db`)
Two new tables/updates are required:
1. **`contacts` Table**:
   - `chat_id` (TEXT, PRIMARY KEY): The WhatsApp serialized ID.
   - `display_name` (TEXT): The name of the contact/group.
   - `last_seen` (DATETIME): Timestamp of the last interaction.
   - *Purpose*: Provides a dedicated source of truth for name $\rightarrow$ ID resolution. Populated incrementally as messages are sent/received.

2. **`whatsapp_proposals` Table**:
   - `proposal_id` (TEXT, PRIMARY KEY): Unique ID for the proposal.
   - `chat_id` (TEXT): The target WhatsApp ID.
   - `recipient_name` (TEXT): The name of the recipient for confirmation.
   - `message_text` (TEXT): The content to be sent.
   - `status` (TEXT): `pending`, `sent`, or `cancelled`.
   - *Purpose*: Stores the state of a message awaiting user approval.

### B. WhatsApp Server (`whatsapp_server/index.js`)
- **Contact Sync**: Update the `message_create` event listener to automatically upsert any interacting chat into the `contacts` table.
- **API**: Continue using the existing `/send-message` endpoint for final execution.

### C. Core Brain (`core_brain.py`)
Two new tools will be added to `ADMIN_TOOLS`:
1. **`find_whatsapp_chat(name)`**:
   - Queries the `contacts` table using `LIKE %name%`.
   - Returns a list of matching names and their `chat_id`s. (Simple substring match is sufficient; no automatic fuzzy retry is required).
2. **`propose_whatsapp_message(chat_id, recipient_name, message)`**:
   - Inserts a record into `whatsapp_proposals`.
   - Returns a formatting tag containing the ID, e.g., `[Proposal: <proposal_id>]`.

### D. Telegram Bot (`bot.py`)
- **UI Integration (Response Parsing)**:
  - When sending messages in `send_long_message`, the bot will search for the pattern `[Proposal: <proposal_id>]` in the LLM's response.
  - If found, the bot will strip the tag from the text (so the raw ID is hidden from the user) and attach an `InlineKeyboardMarkup` directly to that message with `✅ Send` and `❌ Cancel` buttons.
- **Callback Handling**:
  - `wa_send_{id}`: Retrieves message from `whatsapp_proposals` $\rightarrow$ Calls Node.js `/send-message` $\rightarrow$ Removes the buttons and updates the message text to show *"✅ Message sent to [Name]!"*.
  - `wa_cancel_{id}`: Marks proposal as cancelled $\rightarrow$ Removes the buttons and updates the message text to show *"❌ Message cancelled."*.

## 3. User Workflow

1. **Request**: User says: *"Send 'Hi' to John."*
2. **Resolution**: LLM calls `find_whatsapp_chat("John")`.
3. **Ambiguity Check**: 
   - If multiple Johns exist, LLM asks: *"Which John did you mean?"*
   - If one John exists, LLM proceeds.
4. **Proposal**: LLM calls `propose_whatsapp_message(...)` and responds: *"I've prepared the message for John Doe. Please confirm below: [Proposal: 12345]"*
5. **UI Interception**: `bot.py` intercepts `[Proposal: 12345]`, strips it, and displays:
   > *I've prepared the message for John Doe. Please confirm below:*
   > `[ ✅ Send ]`  `[ ❌ Cancel ]`
6. **Execution**: User taps `✅ Send` on the Telegram button. The bot sends the message via WhatsApp and updates the message UI.

## 4. Safety Guardrails & Reliability
- **SQLite Concurrency**: Connect to the SQLite database with a `timeout=10.0` parameter in Python to prevent concurrent read/write locks between the Python and Node.js processes.
- **RBAC**: Tools are strictly restricted to `ADMIN_TOOLS` (Telegram sessions only).
- **Mandatory Confirmation**: The LLM is instructed via tool descriptions to always use the proposal tool rather than direct sending.
- **Single-use Buttons**: Once tapped, the inline keyboard is removed (`reply_markup=None`) to prevent duplicate clicks or double-sends.
