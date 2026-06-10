# Plan: WhatsApp Autoresponder — Conversation Context Awareness

## Objective
Before responding to an incoming message, retrieve recent message history from the same chat to give the LLM context. This helps the bot understand ongoing conversations, references to prior messages, and the flow of the discussion.

## Current Behavior
The agent receives only the single incoming message and responds based on that + session memory. Session memory only tracks the bot's own prior interactions, not the full conversation between other participants.

## Proposed Behavior
When a message arrives, fetch the last N messages from that chat (excluding the bot's own messages) and include them as context for the LLM.

## Implementation

### Data Source
- `whatsapp_messages` table already stores all messages with: sender, text, timestamp, group_id, group_name
- Simple query: `SELECT sender, text, timestamp FROM whatsapp_messages WHERE group_id = ? ORDER BY timestamp DESC LIMIT ?`

### Where It Fits
In `whatsapp_agent.py`, after access control and rate limiting, before the LLM call:
1. Query the DB for last N messages from the chat
2. Format them as a context block
3. Inject into the system prompt or as a pre-context message

### Context Format
```
RECENT CONVERSATION HISTORY (last 10 messages):
[14:30] [Contact]: hey are you coming to dinner tonight?
[14:31] Paddu: yes we're all going
[14:32] [Contact]: great, let me know [Owner]'s plan
[14:33] [Contact]: @[Owner] you coming?
```

### Configuration
Add to `autoresponder_config.json`:
```json
"context_window": {
  "private_message_count": 10,
  "group_message_count": 10,
  "enabled": true
}
```

### Changes Required

#### 1. `autoresponder_config.json`
- Add `context_window` settings (message count for private vs group, enable/disable flag)

#### 2. `whatsapp_agent.py` — Context Fetching
- After rate limiting, query `whatsapp_messages` for last N messages from the chat
- Format as a timestamped conversation log
- Inject into the system prompt (both group and private variants) as a "RECENT CONVERSATION HISTORY" block
- Exclude the bot's own messages (identified by `[🤖]` prefix or known bot sender ID)

#### 3. `whatsapp_agent.py` — System Prompt Update
- Add a context section to both system prompts showing the recent history
- Instruct the LLM to use the context to understand references, ongoing topics, and tone

## Decisions
1. **DB access**: Direct from Python via `sqlite3.connect()` with `timeout=10.0` — same pattern used everywhere else.
2. **Token cost**: No char cap needed — 10 messages is negligible.
3. **Deduplication**: Not needed — `message_id` is unique and uses `INSERT OR IGNORE`.
4. **Session memory**: Complementary, not redundant. Session = bot's own conversation history. Context = other people's messages. WhatsApp autoresponder only — does not apply to the Telegram side.

*Last updated: 2026-05-30*
