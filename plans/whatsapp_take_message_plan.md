# Plan: WhatsApp "Take a Message" Feature

## Objective
When someone messages the owner (directly or in a group) and the autoresponder can't meaningfully respond, it should "take a message" — save it to the DB, optionally acknowledge in-chat, and let the owner retrieve it later via Telegram.

## How It Works

### Trigger Conditions
The autoresponder should take a message (instead of just staying silent) when:
1. **Explicit request**: "tell [Owner] to call me", "let [Owner] know I'm running late", "ask [Owner] if he can make it", "pass this to [Owner]"
2. **LLM judgment**: The message is clearly meant for [Owner] but the bot can't answer (e.g., personal questions, urgent requests)

**Never** auto-take all messages just because the owner is Away/Busy. Only take messages when explicitly requested or when the LLM determines the message is directly for [Owner].

### Acknowledgment
When a message is taken, the bot responds in-chat with something like:
- *"got it, i'll pass that along to [Owner]"* (casual, no bot-speak)
- This gives the sender confidence their message was received

### Storage
New table `messages_for_owner` in `whatsapp.db`:
```sql
CREATE TABLE messages_for_owner (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sender_name TEXT,
    sender_id TEXT,
    chat_name TEXT,           -- group name or "Private Chat"
    chat_id TEXT,
    message_text TEXT,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    read_status TEXT DEFAULT 'unread'  -- 'unread' | 'read' | 'dismissed'
);
```

### Owner Retrieval (Telegram)
- **Tool**: `get_pending_messages()` — returns unread messages formatted for the LLM
- **Natural language**: Owner asks *"any messages for me?"* or *"what did people say?"*
- Bot retrieves from DB and presents: sender, context (group/private), message, time
- **Tool**: `mark_message_read(id)` or `clear_all_messages()` — mark as read or bulk clear

### Notification (Optional)
Two approaches:
- **Passive**: Owner checks on their own via Telegram ("any messages?")
- **Proactive**: Bot sends a Telegram notification when a message is taken — *"📝 [[Contact]] said: 'tell [Owner] to call me back' (from Expat Dads group)"*

## Changes Required

### 1. `whatsapp.db` — New Table
- Create `messages_for_owner` table via `whatsapp_server/index.js` init

### 2. `whatsapp_agent.py` — Message-Taking Logic
- After LLM response, check if the response is the fallback message OR the system prompt signals "take message"
- If so: insert into `messages_for_owner` via a new internal API endpoint (or direct DB access)
- Send acknowledgment response in-chat instead of staying silent
- If owner is "Away"/"Busy": always take the message, skip LLM entirely

### 3. `core_brain.py` — New Tools
- `get_pending_messages()` — ADMIN tool, queries unread messages from DB
- `clear_messages(ids)` — ADMIN tool, marks messages as read/dismissed

### 4. `whatsapp_server/index.js` — Optional Notification Endpoint
- If proactive notifications are wanted: POST to a new Telegram notification endpoint after inserting a message

## Decisions
1. **Acknowledge in both groups and private** — bot always responds with a casual acknowledgment when taking a message, regardless of chat type.
2. **Passive notification only** — no proactive Telegram pushes. Owner retrieves messages on demand. Daily digest can be scheduled using the existing scheduler + `get_pending_messages()` tool (e.g., "send me my pending WhatsApp messages every day at 8pm").
3. **Manual clear** — no auto-expiry. Owner clears messages via `clear_messages()` when done.

*Last updated: 2026-05-30*
