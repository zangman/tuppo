# 🛠️ Worklog: Telegram Bot Enhancement Session

This document tracks all changes implemented during the current development session.

## 1. Telegram Message Length & Robustness
- **Problem**: Bot crashed when LLM responses exceeded Telegram's 4096 character limit.
- **Solution**: Implemented a sophisticated chunking system.
  - Added `split_markdown()`: Splits raw LLM output into safe chunks (~3500 chars) while preserving paragraph structure.
  - Added `send_long_message()`: Handles the sequential sending of chunks to Telegram and ensures performance metrics (TPS) are only appended to the final message.

## 2. Local Web Search Integration (SearXNG)
- **Goal**: Replace/Supplement Exa.ai with a locally hosted SearXNG instance.
- **Implementation**:
  - Created `tools/searxng_search.py`: A tool that queries `http://localhost:8081/search` in JSON format.
  - Integrated `searxng_search` into `bot.py`.
  - Commented out `web_search` (Exa) in the system prompt to make SearXNG the primary search engine.

## 3. WhatsApp Ingestion Server
- **Goal**: Ability to log and summarize WhatsApp group activity.
- **Implementation**:
  - Created a standalone Node.js server in `/whatsapp_server/`.
  - Used `whatsapp-web.js` with `LocalAuth` for persistent session management.
  - Implemented a local SQLite database (`whatsapp.db`) to store messages.
  - **Noise Filtering**: 
    - Implemented a filter to ignore empty system notifications.
    - Added media labels (e.g., `[Media: image]`) for messages with attachments but no text.
    - Added a filter to ignore `reaction` type messages to prevent database clutter.

## 4. WhatsApp Summary Tool
- **Goal**: Allow the LLM to read and summarize WhatsApp history.
- **Implementation**:
  - Created `tools/whatsapp_summary.py`.
  - Implemented `get_whatsapp_transcript()`:
    - Can list active chats if no specific query is provided.
    - Fetches chronological transcripts for specific groups/chats using partial name matches.
  - Integrated the tool into `bot.py`'s `execute_tool` router.

## 5. WhatsApp "Bookmark" System (Last Read Tracking)
- **Goal**: Prevent the LLM from reading the same messages repeatedly in every summary.
- **Implementation**:
  - Added `chat_status` table to the SQLite DB to track the `last_read_timestamp` per chat.
  - Updated `get_whatsapp_transcript` to fetch only the "delta" (messages arrived since the last bookmark).
  - Implemented an automatic update of the bookmark after every successful transcript retrieval.

## 6. Google Calendar Integration (Full CRUD)
- **Goal**: Enable the bot to manage the user's schedule across multiple calendars.
- **Implementation**:
  - **OAuth2 Flow**: Implemented a secure authentication system using `credentials.json` and `token.json` for persistent, headless access.
  - **Multi-Calendar Support**: Created `list_user_calendars` to discover all accessible calendars (e.g., "Home", "Work").
  - **Aggregated Reading**: Enhanced `list_calendar_events` with an `'all'` keyword to fetch and merge events from all calendars into a single chronological timeline.
  - **Event Creation**: Implemented `create_calendar_event` allowing the bot to schedule events in any specified calendar.
  - **Event Deletion**: Implemented `delete_calendar_event` using unique `eventId`s to remove specific entries.
  - **Partial Updates**: Implemented `update_calendar_event` using the `patch` method, allowing the bot to change only specific fields (title, time, or description) without overwriting the rest of the event.

## 7. Core Brain Refactoring & Session Isolation
- **Goal**: Resolve context leakage between different users/channels and centralize LLM logic.
- **Implementation**:
  - Extracted all tool routing and LLM communication from `bot.py` into a new `core_brain.py` module.
  - Implemented **Session-Based Memory**: Use unique session IDs (e.g., `tg_{id}`, `wa_{id}`) to maintain separate conversation histories.
  - Centralized tool registration and `execute_tool` logic to be shared across multiple interfaces (Telegram and WhatsApp).

## 8. Dynamic Owner Profile System
- **Goal**: Give the bot a way to know the owner's current status/context without manual prompting.
- **Implementation**:
  - Created `owner_profile.json` to store current location, availability, and focus.
  - Implemented `tools/owner_profile.py` with `get_profile` and `update_owner_status` functions.
  - Integrated the profile as a primary context source for the AI assistant.

## 9. WhatsApp Autoresponder Architecture
- **Goal**: Implement an intelligent, non-intrusive autoresponder.
- **Implementation**:
  - **Node.js Gateway**: Upgraded `whatsapp_server` to include an Express API (`/send-message`) and a webhook forwarder that pushes incoming private messages to the Python agent.
  - **Configuration**: Created `autoresponder_config.json` to manage `allowed_targets`, response delays, and fallback messages.
  - **Agent Webhook**: Built `whatsapp_agent.py` using FastAPI to receive webhooks, synthesize context (Profile + Calendar + History), and trigger responses.

## 10. Loop Prevention & Stealth Logic
- **Goal**: Avoid "bot-on-bot" loops and make the bot feel more human.
- **Implementation**:
  - **Safety Fuse**: Implemented a message-rate limiter in `whatsapp_agent.py` that disables responses if more than 3 messages are received from a user within 60 seconds.
  - **Delayed Response**: Added a randomized delay (configured in JSON) before sending responses to mimic human typing speed.
  - **Silent Fallback**: Modified the logic so that if the LLM cannot find a factual answer, the bot remains completely silent instead of sending a canned "away" message.

## 11. AI Persona Transition: "Assistant" Mode
- **Goal**: Move from a strict "Fact-Checker" to a helpful Personal Assistant.
- **Implementation**:
  - Refined the system prompt in `whatsapp_agent.py` to encourage proactive help and social intelligence.
  - Enabled the bot to handle greetings and small talk politely while still maintaining boundaries regarding the owner's personal life.

## 12. Calendar Timezone & Stability Fixes
- **Problem**: Calendar events were being shifted by several hours (e.g., 6:30 PM $\rightarrow$ 2:30 AM) because the LLM generated UTC timestamps (`Z` suffix), which Google interpreted as UTC regardless of the specified timezone.
- **Solution**: 
  - Implemented a `sanitize_iso` utility in `tools/google_calendar.py` to strip UTC offsets (`Z`, `+HH:mm`) from timestamps, forcing Google to treat them as local time in the owner's configured timezone.
  - Fixed a `SyntaxError` in `tools/google_calendar.py` caused by accidental escaping of docstrings during a file write operation.
- **Robustness**: 
  - Fixed a Telegram `400 Bad Request` parsing error in `propose_calendar_event`.
  - Switched from `Markdown` to `HTML` parse mode and implemented `html.escape()` for all dynamic fields (summary, requester ID, etc.) to prevent crashes when users input special characters.

## 13. Autoresponder Control & Identity Personalization
- **Goal**: Allow the owner to toggle the autoresponder and define a clear identity for the AI.
- **Implementation**:
  - **Dynamic Toggle**:
    - Added `enabled` flag to `autoresponder_config.json` to act as a global kill-switch.
    - Implemented `/wa_on` and `/wa_off` commands in `bot.py` to allow the owner to enable/disable the autoresponder via Telegram.
    - Updated `whatsapp_agent.py` to exit early if the `enabled` flag is false.
  - **Identity Personalization**:
    - Added `"name": "[Owner]"` to `owner_profile.json`.
    - Updated the system prompt in `whatsapp_agent.py` to define the bot as "[Owner]'s Personal Assistant," ensuring it represents the owner correctly and refers to him by name.

## 14. Natural & Conversational Tone Implementation
- **Goal**: Remove robotic "customer service" friction and make the bot sound like a relaxed, natural human assistant.
- **Implementation**:
  - **Anti-Corporate Filter**: Updated the system prompt in `whatsapp_agent.py` to strictly forbid AI-isms (e.g., "How may I assist you?") and replace them with natural, casual alternatives.
  - **Match the Energy**: Instructed the bot to handle simple greetings and small talk naturally and briefly, without over-offering services.
  - **Brevity & Grammar**: Enforced a 1-2 sentence maximum and encouraged relaxed grammar (contractions, occasional lowercase starts) to mimic real phone texting.
  - **Humanized Fallback**: Updated `fallback_message` in `autoresponder_config.json` to be more casual and less formal.
- **Bug Fix**: Resolved a `json.decoder.JSONDecodeError` by removing a trailing comma from `autoresponder_config.json`.

## 15. Scheduling & Automation Engine
- **Goal**: Enable the owner to automate tasks, reminders, and dynamic reports via Telegram.
- **Implementation**:
  - **Database-as-Queue Architecture**: Created a `scheduled_tasks` table in `whatsapp.db` to persist one-time and recurring tasks across restarts.
  - **Background Worker**: Implemented `scheduler_manager.py` as an async background loop in `bot.py` that polls the database every 30 seconds.
  - **Tooling**: Added `schedule_task`, `list_scheduled_tasks`, and `cancel_scheduled_task` to `core_brain.py` for LLM control.
  - **Cron Integration**: Integrated `croniter` to support complex recurring schedules (e.g., "every day at 6AM and 6PM").
  - **Early Identity Resolution**: Enforced a rule requiring the LLM to resolve WhatsApp names/groups to exact `chatId`s *before* scheduling to prevent runtime ambiguity.
  - **Dynamic LLM Tasks**: Implemented the `llm_task` action, allowing the bot to defer tool execution (e.g., "Fetch latest news") until the scheduled time, ensuring the information is fresh.
- **Stability Fixes**:
  - **Timezone Unification**: Unified all storage and comparisons to **UTC** to prevent string-comparison failures between SGT and UTC timestamps.
  - **Action Clarification**: Renamed actions to `send_whatsapp_message` and `send_telegram_reminder` to prevent the LLM from confusing the two platforms.
  - **Venv Management**: Properly installed dependencies in the project's virtual environment (`v/`).

## 16. Telegram-to-WhatsApp Messaging with Confirmation
- **Goal**: Allow the owner to send WhatsApp messages via Telegram with a human-in-the-loop approval step.
- **Implementation**:
  - **Database**: Added `contacts` table (auto-populated by WhatsApp server on every message) and `whatsapp_proposals` table (pending messages awaiting approval) to `whatsapp.db`.
  - **Contact Sync**: Updated `whatsapp_server/index.js` to upsert every interacting chat into the `contacts` table for name → ID resolution.
  - **`find_whatsapp_chat(name)`** (new ADMIN tool): Queries `contacts` with `LIKE %name%` to resolve contacts/groups by name.
  - **`propose_whatsapp_message(chat_id, recipient_name, message_text)`** (new ADMIN tool): Inserts a proposal record and returns a `[Proposal: <id>]` tag.
  - **UI Interception**: `send_long_message()` in `bot.py` detects the `[Proposal: <id>]` tag, strips it from visible text, and attaches ✅ Send / ❌ Cancel inline buttons.
  - **Callback Handling**: Extended `handle_event_proposal` to handle `wa_send_{id}` (sends via WhatsApp gateway, marks as `sent`) and `wa_cancel_{id}` (marks as `cancelled`), removing buttons on use.
- **Safety**: `timeout=10.0` on all SQLite connections to prevent Node.js/Python lock contention. RBAC restricts tools to admin sessions only.
  - **Coded Confirmation Block**: When `send_long_message()` detects a `[Proposal: <id>]` tag, it fetches the proposal from the DB and appends a confirmation block showing the exact recipient and message text. This ensures the owner always sees what will actually be sent, regardless of how the LLM phrases its response.

## 17. Automatic Scheduling Confirmation
- **Goal**: Ensure the owner always sees the exact details of any scheduled task before it executes, without relying on the LLM to volunteer the info.
- **Implementation**:
  - Added `_send_scheduling_confirmation()` in `core_brain.py` that fires automatically after every `schedule_task` call.
  - Sends a Telegram notification with: task ID, action type, execution time (converted to local timezone), recurrence (if cron), and exact message text / task details.
  - Uses `html.escape()` on all dynamic content to prevent parse errors.
  - Completely independent of the LLM — no prompt engineering needed.

## 17a. Scheduler WhatsApp Send Response Check
- **Problem**: The scheduler always reported "✅ sent" for `send_whatsapp_message` tasks regardless of whether the WhatsApp API call actually succeeded.
- **Solution**: Added response status checking in `scheduler_manager.py`. Now reports exact success/failure counts (e.g., "✅ Sent to 1. ❌ Failed: 0.").

## 18. WhatsApp Group Autoresponder (Mention-Triggered)
- **Goal**: Respond in WhatsApp groups only when the owner is explicitly @mentioned or replied to.
- **Implementation**:
  - **`owner_profile.json`**: Added `owner_whatsapp_id` field for mention matching.
  - **`autoresponder_config.json`**: Added `allowed_groups` list to control which groups trigger autoresponse.
  - **`whatsapp_server/index.js`**: In `message_create`, for group chats in the allowlist: triggers autoresponse if owner is @mentioned **or** if someone replies to the owner's message (`msg.hasQuotedMsg` → checks quoted sender). Forwards to Python agent with `isGroup: true` flag.
  - **`whatsapp_agent.py`**: Group sessions use `wa_group_<groupId>` for isolation. Separate system prompt optimized for group context (1-sentence responses, silent on failure). Extra safety: skips responses >2 sentences in groups.
  - **`bot.py`**: Added `/wa_groups` (list allowed groups), `/wa_group_add <name>` (add group via name search), `/wa_group_remove <name>` (remove from allowlist).
  - **Bot Identity**: All autoresponder responses are prefixed with `[🤖] ` so recipients know it's not [Owner]. LLM is instructed not to add the prefix itself.

## 18a. Safety Fuse Configuration
- **Goal**: Make rate limits adjustable without code changes.
- **Implementation**: Moved safety fuse settings from hardcoded values in `whatsapp_agent.py` to `autoresponder_config.json` under `safety_fuse`:
  - `private_max_messages` / `private_window_seconds` (3 per 60s)
  - `group_max_per_sender` / `group_window_seconds` (2 per 60s)

## 18c. WhatsApp "Take a Message" Feature
- **Goal**: Allow the autoresponder to take messages for the owner when someone explicitly asks (e.g., "tell [Owner] to call me", "let [Owner] know...").
- **Implementation**:
  - **`whatsapp.db`**: Added `messages_for_owner` table (id, sender_name, sender_id, chat_name, chat_id, message_text, timestamp, read_status).
  - **`whatsapp_server/index.js`**: Added `/take-message` API endpoint for the Python agent to save messages.
  - **`whatsapp_agent.py`**: Added `TAKE_MESSAGE` signal to system prompts (both group and private). When the LLM responds with exactly `TAKE_MESSAGE`, the agent saves the original message to the DB and sends a casual acknowledgment in-chat: "[🤖] got it, i'll pass that along to [Owner]".
  - **`core_brain.py`**: Added `count_pending_messages()` (ADMIN tool) to return just the count of unread messages. Added `get_pending_messages()` (ADMIN tool) to retrieve full message details. Added `clear_messages()` (ADMIN tool) to mark messages as read (all or by ID).
- **Decisions**: Acknowledge in both groups and private. Passive notification only (no proactive Telegram pushes — owner can schedule daily digest using existing scheduler). Manual clear only (no auto-expiry).

## 18b. Contacts Table Backfill
- **Problem**: The `contacts` table was missing groups/chats that had messages before the upsert code was deployed.
- **Solution**: Ran one-time backfill: `INSERT OR IGNORE INTO contacts (chat_id, display_name) SELECT DISTINCT group_id, group_name FROM whatsapp_messages;`

## 18e. Conversation Context Awareness (Autoresponder)
- **Goal**: Give the LLM recent conversation history before responding, so it understands ongoing topics and references.
- **Implementation**:
  - **`autoresponder_config.json`**: Added `context_window` config (enabled, private_message_count: 10, group_message_count: 10).
  - **`whatsapp_agent.py`**: Added `fetch_recent_context()` helper that queries `whatsapp_messages` for last N messages (DESC + LIMIT), reverses to oldest-first for natural reading order, formats as timestamped conversation log, skips bot's own `[🤖]` messages, truncates long messages at 150 chars. Injects context block into both group and private system prompts.
  - **Debug logging**: Full system prompt (including context block) is logged before each LLM call.
- **Scope**: WhatsApp autoresponder only — does not apply to the Telegram side.

## 18d. Sender Name Resolution
- **Problem**: Both "take a message" and calendar proposals showed raw WhatsApp IDs (e.g., `<contact_id>@lid`) instead of display names in the "From" field.
- **Solution**: Both `whatsapp_server/index.js` (`/take-message`) and `tools/google_calendar.py` (`propose_calendar_event`) now look up the sender's display name from the `contacts` table before saving/displaying. Falls back to raw ID if no match.

## 19. Keep WhatsApp Chats Unread After Bot Processing
- **Problem**: When the bot processes incoming private messages via WhatsApp Web, the messages are automatically marked as read, so they no longer show as unread on the owner's phone.
- **Solution**: `chat.markUnread()` in `whatsapp_server/index.js` only fires when the autoresponder sends a response (via `mark_unread: True` flag on `/send-message`). If the owner responds directly in the app, the chat is not marked unread.
- **Scope**: Private chats only — group chats are unaffected.

## 20. Bot Identity Prefix Change
- **Change**: Removed square brackets from the bot prefix. All autoresponder responses now use `🤖 ` instead of `[🤖] `.

## 21. Schedule Task Validation
- **Problem**: The LLM could call `schedule_task` with no `execution_time` or `cron_expression`, creating tasks that would never execute (e.g., "Time: None"). It also confused `schedule_task` with immediate sending.
- **Solution**: Added validation in `core_brain.py` — `schedule_task` now rejects calls with neither `execution_time` nor `cron_expression`. Updated tool description to explicitly say "Do NOT use this to send messages immediately — use propose_whatsapp_message for that."

## 22. Robot Emoji Prefix for All Bot-Sent Messages
- **Problem**: Scheduled WhatsApp messages and approved proposals were sent without the `🤖 ` prefix, making them indistinguishable from the owner's own messages.
- **Solution**: Added `🤖 ` prefix in all three WhatsApp sending paths:
  - **`scheduler_manager.py`**: `send_whatsapp_message` action prefixes text before sending
  - **`bot.py`**: Proposal approval (`wa_send_` callback) prefixes message text before sending
  - **`whatsapp_agent.py`**: Autoresponder responses (already had this)

## 23. Proposal Tag Reliability
- **Problem**: After calling `propose_whatsapp_message`, the LLM was generating extra conversational text (e.g., "Your message has been proposed...") which either lost the `[Proposal: <id>]` tag or stripped the square brackets, preventing inline buttons from appearing.
- **Solution**: In `core_brain.py`'s `get_llm_response()`, when `propose_whatsapp_message` is called, the `[Proposal: <id>]` tag is returned directly without letting the LLM generate additional text. Added system prompt instruction reinforcing that only the tag should be output after this tool call.

## 24. SQL IN Clause Fix for /wa_group_remove
- **Problem**: `/wa_group_remove` crashed with a SQL error because `IN ?` doesn't accept a list directly in SQLite.
- **Solution**: Fixed `bot.py` to generate dynamic placeholders `(?, ?, ?)` for each item in the allowed groups list. Also handles the edge case where `allowed_groups` is empty.

## 25. /wa_list Command
- **Goal**: List all WhatsApp contacts/groups without involving the LLM.
- **Implementation**: Added `/wa_list` command in `bot.py`:
  - `/wa_list` — all contacts (groups + private) with chat IDs
  - `/wa_list groups` — groups only
  - `/wa_list private` — private chats only
- Queries the `contacts` table directly, sorted alphabetically.

## 26. Conditional Reasoning Content by Model Family
- **Problem**: llama.cpp returns `reasoning_content` in assistant messages (via `reasoning_format: auto`). This was always stored in session memory and re-sent on every turn. Qwen models benefit from seeing their own prior reasoning, but Gemma models do not (and may degrade).
- **Solution**: Added model-aware reasoning stripping in `core_brain.py`:
  - `_get_loaded_model()`: Fetches the currently loaded model name via `GET /v1/models` before each request
  - `_needs_reasoning_in_history(model_name)`: Case-insensitive check — returns `True` if `"qwen"` is in the model name
  - `_strip_reasoning(messages)`: Returns a copy of the message list with `reasoning_content` keys removed
  - `get_llm_response()` now conditionally strips reasoning from the outgoing payload based on the loaded model
  - Session memory is never mutated — reasoning is always stored, only the payload is filtered
  - Both initial payload and loop continuation (`payload["messages"] = ...`) go through the same logic
- **Safety**: Falls back to keeping reasoning if llama.cpp is unreachable (safe default)
- **Dynamic**: Detects model on every request, so model swaps are handled transparently without restart

## 27. Split WhatsApp Transcript into Delta Fetch + History Search
- **Problem**: The single `get_whatsapp_transcript()` tool used a shared bookmark (`last_read_timestamp` per chat). This meant:
  - Historical lookups ("what address was mentioned 2 days ago?") were impossible — only messages since the bookmark were returned
  - Scheduled summaries and manual queries competed for the same bookmark, causing messages to be skipped
  - No keyword/topic search capability existed
  - Bug: `datetime('now', '-X hours')` was passed as a `?` parameter, making SQLite treat it as a literal string (always returned 0 results for time-range queries)
- **Solution**: Split into two tools in `tools/whatsapp_summary.py`:
  - **`get_new_messages(chat_name_query)`** (PUBLIC) — Bookmark-based delta fetch. Returns only unread messages since last check. Advances the bookmark. Use for "what's new?" / "give me an update".
  - **`get_chat_history(chat_name_query, timeframe_hours, search_text)`** (ADMIN) — Arbitrary range fetch with optional keyword filter. Does NOT use or advance the bookmark. Use for "find messages about X" or "show me the last 2 days".
  - Added `_resolve_chat()` helper to deduplicate chat-matching logic
  - Added output truncation at 3500 chars with `[Truncated: showing X of Y messages]` notice
  - Fixed SQLite `datetime()` bug by embedding the time expression directly in SQL instead of as a parameter
- **Tool definitions** updated in `core_brain.py` with distinct descriptions to guide the LLM to the right tool
- **Scheduler** `send_summary` action now uses `get_chat_history()` instead of the bookmark-based function, eliminating bookmark collision between scheduled and manual queries

## 28. Sliding Window Token Budget for Session Context
- **Problem**: Session memory (`sessions[session_id]`) grew without bound. Every user message, assistant response, tool call, and tool result was appended and re-sent on every LLM request. After many turns, payloads became bloated with stale context, wasting the 131k context window and slowing inference.
- **Solution**: Added `_limit_tokens(messages, max_tokens)` in `core_brain.py`:
  - Approximate token counting via `len(content) / 4` (no extra dependency)
  - Always preserves system prompt (index 0)
  - Evicts from the oldest end — groups assistant tool_calls + tool results into atomic blocks so no orphaned tool messages are created
  - Applied at send time only — session storage is never mutated
  - Applied in both initial payload construction and the tool-call loop continuation
  - Cap: `_MAX_CONTEXT_TOKENS = 32768` (configurable constant, leaves ~98k for tool definitions and generation)

## 29. Fix Scheduled WhatsApp Messages Sending Empty Text
- **Problem**: Scheduled `send_whatsapp_message` tasks always sent empty messages. The confirmation card showed "Message: (empty)" and the actual WhatsApp delivery was blank, even though `message_text` was stored correctly in the DB.
- **Root cause**: Key mismatch — the tool schema defines `message_text`, but `_send_scheduling_confirmation()` and `scheduler_manager.py` both read `params.get('text')`. Broken since scheduled WhatsApp messages were first implemented (`7fdc619`).
- **Fix**: Both sites now read `params.get('message_text', params.get('text', ...))` — prefers the correct key, falls back to `text` for backward compat.

## 30. Fix Scheduled Telegram Reminders Showing Empty Text
- **Problem**: Scheduled `send_telegram_reminder` tasks showed "Reminder: (empty)" in the confirmation card, and the actual scheduled delivery would send blank or fallback text.
- **Root cause**: Same key mismatch as #29 — the LLM passes `message_text` in `params`, but `_send_scheduling_confirmation()` and `scheduler_manager.py` both read `params.get('text')`. The vague tool schema ("use chat_ids and text") lets the LLM freely choose key names.
- **Fix**: Both sites now read `params.get('message_text', params.get('text', ...))` — prefers `message_text`, falls back to `text` for backward compat.

## 31. Explicit Params Schema Per Action Type
- **Problem**: The `schedule_task` tool schema had a vague `params` description ("use chat_ids and text") that let the LLM freely choose key names, resulting in inconsistent params (`text`, `message_text`, `message`) across calls.
- **Fix**: Updated the tool schema to specify exact keys per action type:
  - `send_telegram_reminder` → `{'message_text': '...'}`
  - `send_whatsapp_message` → `{'recipients': ['<chatId>'], 'message_text': '...'}`
  - `send_summary` → `{'group': '<name>', 'timeframe_hours': <int>}`
  - `llm_task` → `{'prompt': '...'}`

## 32. Unified `message_text` Key Across All Scheduled Actions
- **Change**: Standardized on `message_text` as the single key for message content in both `send_telegram_reminder` and `send_whatsapp_message`.
- **Cleanup**: Removed all fallback key handling (`text`, `message`) from `_send_scheduling_confirmation()` and `scheduler_manager.py`. Code now reads `params.get('message_text')` only.
- **Impact**: Existing DB entries using old keys will show empty — owner can recreate tasks if needed.

## 33. Split `schedule_task` into Four Explicit Tools
- **Problem**: The single `schedule_task` tool used a generic `params: {type: object}` with no schema constraints. The LLM freely chose key names (`text`, `message`, `message_text`) making the code unreliable.
- **Solution**: Replaced `schedule_task` with four separate tools, each with explicit JSON Schema properties:
  - `schedule_telegram_reminder(message_text, execution_time?, cron_expression?)`
  - `schedule_whatsapp_message(recipients[], message_text, execution_time?, cron_expression?)`
  - `schedule_summary(group, timeframe_hours?, execution_time?, cron_expression?)`
  - `schedule_llm_task(prompt, execution_time?, cron_expression?)`
- **Handler**: Single execute_tool branch handles all four via an `action_map` to DB action types.
- **DB compat**: Same `scheduled_tasks` table, same action_type values — existing tasks unaffected.
- **Confirmation/Scheduler**: Already read `message_text` — no changes needed.

## 34. Calendar Name Alias Resolution + Unified Event Listing
- **Problem**: The LLM needed 2 tool calls to create an event in the home calendar (first `list_user_calendars` to get the ID, then `create_calendar_event`). `list_calendar_events` required specifying a `calendar_id` even when the owner just wants to see everything.
- **Solution**:
  - Added `_resolve_calendar_id()` in `tools/google_calendar.py` — maps `"primary"` → Google's `'primary'` keyword, `"home"` → `home_calendar_id` from `owner_profile.json`, passthrough for explicit IDs.
  - Applied resolution in `create_calendar_event()`, `delete_calendar_event()`, `update_calendar_event()`.
  - Rewrote `list_calendar_events()` — removed `calendar_id` parameter. Always fetches from primary + home calendars, merges and sorts by start time, tags each event with `[Primary]` or `[Home]` label.
  - Updated tool schemas in `core_brain.py`: `create/delete/update` now use `enum: ["primary", "home"]` for `calendar_id`. `list_calendar_events` no longer accepts `calendar_id`.
- **Impact**: LLM makes a single call for all calendar operations — no ID lookup needed.

## 35. Split WhatsApp-Only Tools From PUBLIC_TOOLS + Rename schedule_summary
- **Problem**: `propose_calendar_event` and `check_owner_availability` were in `PUBLIC_TOOLS`, making them available to both Telegram and WhatsApp LLMs. The Telegram LLM didn't need these and they were confusing smaller models.
- **Solution**:
  - Moved `propose_calendar_event` and `check_owner_availability` out of `PUBLIC_TOOLS` into a new `_WHATSAPP_ONLY_TOOLS` list.
  - Created `WHATSAPP_TOOLS = PUBLIC_TOOLS + _WHATSAPP_ONLY_TOOLS`.
  - Updated RBAC in `execute_tool()` and `get_llm_response()` to 3-tier: `tg_*` → `ADMIN_TOOLS`, `wa_*` → `WHATSAPP_TOOLS`, fallback → `PUBLIC_TOOLS`.
  - Renamed `schedule_summary` → `schedule_whatsapp_summary` for clarity (it only summarizes WhatsApp groups).
- **Impact**: Telegram LLM goes from 24 tools → 23 (loses 2 calendar tools). WhatsApp LLM unchanged at 5 tools.

---
*Last updated: 2026-06-04*
- **Problem**: The LLM needed 2 tool calls to create an event in the home calendar (first `list_user_calendars` to get the ID, then `create_calendar_event`). `list_calendar_events` required specifying a `calendar_id` even when the owner just wants to see everything.
- **Solution**:
  - Added `_resolve_calendar_id()` in `tools/google_calendar.py` — maps `"primary"` → Google's `'primary'` keyword, `"home"` → `home_calendar_id` from `owner_profile.json`, passthrough for explicit IDs.
  - Applied resolution in `create_calendar_event()`, `delete_calendar_event()`, `update_calendar_event()`.
  - Rewrote `list_calendar_events()` — removed `calendar_id` parameter. Always fetches from primary + home calendars, merges and sorts by start time, tags each event with `[Primary]` or `[Home]` label.
  - Updated tool schemas in `core_brain.py`: `create/delete/update` now use `enum: ["primary", "home"]` for `calendar_id`. `list_calendar_events` no longer accepts `calendar_id`.
- **Impact**: LLM makes a single call for all calendar operations — no ID lookup needed.

## 36. Fix Google Calendar Re-Auth (CSRF State Mismatch + Clickable Telegram Link)
- **Problem**: When the Google Calendar token expired, the bot sent a re-auth URL to Telegram, but authorization failed with `(mismatching_state) CSRF Warning!`. The root cause was that `_notify_calendar_auth_needed()` called `flow.authorization_url()` (generating state `A`), while `flow.run_local_server()` generated its own independent state `B`. The callback from the Telegram link carried state `A`, but the local server expected state `B`.
- **Solution**: Replaced the fragile private-method approach with a robust, version-independent duck-typing trick on the public API:
  - Created `TelegramNotificationPrompt` class in `tools/google_calendar.py` that overrides `.format(url)` to intercept the auth URL and forward it to Telegram.
  - Passed this custom object as `authorization_prompt_message` to the standard `flow.run_local_server()` call.
  - `run_local_server()` calls `.format(url=auth_url)` on our object, which triggers the Telegram notification with the **exact same URL** whose state/PKCE values are registered on the `flow` instance.
  - Result: the callback state perfectly matches the server's expected state — zero CSRF errors.
- **Improvement**: Changed the Telegram notification from a raw `<code>` block to a clickable `<a href='...'>click here to authorize</a>` link.
- **Impact**: Re-auth now works reliably on headless/remote servers with no library-version dependencies.

## 37. Configurable LLM Server URL
- **Problem**: The llama.cpp server URL (`http://localhost:8080`) was hardcoded in `core_brain.py` across the endpoint URLs and browser-spoofing headers.
- **Solution**: Added `config.json` with `llm_base_url` key. `core_brain.py` reads it at import time and derives `_URL`, `_MODELS_URL`, and `_HEADERS` (`Referer`, `Origin`) from it. Falls back to `http://localhost:8080` if missing or malformed.
- **Impact**: Server URL/port can be changed by editing a single value in `config.json` — no code changes needed.

## 38. Startup LLM Server Status Check
- **Goal**: Log the LLM server URL and currently loaded model name when the bot starts.
- **Implementation**: Added `_log_llm_server_status()` in `bot.py` that hits `/v1/models` with a 3-second timeout before polling begins. Logs model name on success, warning on failure.
- **Non-fatal**: Bot continues starting even if the server is unreachable (allows starting bot before turning on the LLM server).

## 39. Unified YAML Configuration
- **Problem**: Configuration was scattered across three files (`owner_profile.json`, `autoresponder_config.json`, `config.json`), making changes require editing multiple files and creating drift risk. Python and Node.js each loaded their own subset of configs independently.
- **Solution**: Merged all configuration into a single `config.yaml` with three top-level sections:
  - `owner` — name, chat_id, whatsapp_id, timezone, home_calendar_id, status
  - `llm` — base_url
  - `whatsapp.autoresponder` — enabled, test_mode, allowed_targets, allowed_groups, response_delay, fallback_message, context_window, safety_fuse
- **New module**: `util/config.py` — shared Python YAML loader with in-memory caching, `reload_config()`, and `save_config()` for runtime writes.
- **Files migrated**:
  - `core_brain.py` — reads `llm.base_url` and `owner.*` from `config.yaml`
  - `bot.py` — `/wa_on`, `/wa_off`, `/wa_groups`, `/wa_group_add`, `/wa_group_remove`, `post_init`, `_log_llm_server_status` all use `util.config`
  - `whatsapp_agent.py` — reads `whatsapp.autoresponder.*` and `owner.*` from `config.yaml`
  - `tools/google_calendar.py` — helper functions (`_get_owner()`, `_get_owner_chat_id()`, `_get_owner_timezone()`, `_get_home_calendar_id()`) read from `config.yaml`
  - `tools/owner_profile.py` — reads/writes `owner.status` via `config.yaml`
  - `whatsapp_server/index.js` — uses `js-yaml` to read `config.yaml` for `owner.whatsapp_id` and `whatsapp.autoresponder.allowed_groups`
- **Dependencies added**: `pyyaml` (Python), `js-yaml` (Node.js)
- **Files removed**: `owner_profile.json`, `autoresponder_config.json`, `config.json`
- **Safety**: `config.json` added to `.gitignore` to prevent accidental re-creation
- **Impact**: Single source of truth for all bot configuration. Runtime writes (e.g., `/wa_on`, `/owner_status`) persist back to the same YAML file.

---
*Last updated: 2026-06-06*

## 40. WhatsApp Summary & First-Read Logic Optimization
- **Problem**: "New messages" logic had a cold-start bug where the first call would set the bookmark to "now" and return nothing. Additionally, the LLM often provided transcripts instead of summaries and incorrectly fell back to full history when no new messages were found.
- **Solution**:
  - **First-Read Window**: Modified `get_new_messages` to start the bookmark at the 1,000th most recent message (or the absolute oldest) if no previous bookmark exists.
  - **Output Truncation**: Implemented a 3,500-character limit in `get_new_messages` with a `[Truncated]` notice to prevent Telegram character limit crashes.
  - **Machine-Readable Format**: Removed "pretty" headers and decorative text from tool returns, providing a dense `[Time] Sender: Message` format to optimize LLM token usage.
  - **Summarization-First Prompting**: Updated the system prompt in `core_brain.py` to strictly mandate a synthesis of information (takeaways, action items, decisions) using bullet points.
  - **Explicit Quote Override**: Added a rule allowing the LLM to provide exact quotes or full transcripts only when the user explicitly requests keywords like "quote" or "exact message."
  - **Strict Tool Constraints**: Updated tool descriptions in `core_brain.py` to forbid falling back to `get_whatsapp_history` for general "summary" requests.
  - **Bug Fix**: Resolved a `SyntaxError` (double comma) in `core_brain.py` during tool definition.

## 41. README Documentation Overhaul
- **Goal**: Add proper documentation for onboarding, features, and project context.
- **Implementation**:
  - **`README.md`**: Full rewrite with:
    - Feature overview (Telegram interface, WhatsApp autoresponder, scheduling, tools)
    - Command reference table (all `/` commands with descriptions)
    - Architecture diagram (vertical flows for Telegram and WhatsApp)
    - Message flow descriptions
    - Step-by-step setup guide (dependencies → config → token → BotFather → Google Calendar → WhatsApp gateway → SearXNG → start)
    - Database schema table
    - Limitations section (single user, single WhatsApp, in-memory sessions, local LLM only, no webhook auth, plaintext secrets, SQLite, no encryption, OAuth refresh, two calendars only)
    - Tools Used section (featuring pi.dev)
    - Extendability section (fork + vibe-code, clean-slate branch from hand-coded commit)
    - Coding history note (hand-written until commit `ff356a7`, then AI-assisted with Qwen3.6-27B, Gemma4-31B, occasional Gemini 3.5 Flash)
    - Personal-use disclaimer
    - Experimental caveat on WhatsApp autoresponder
    - Table of contents with clickable links
    - SearXNG Docker install step with link to official docs
    - BotFather `/setcommands` registration step
- **`plans/README.md`**: Added README explaining design docs purpose, Gemini 3.5 Flash cross-reviews, and implementation status table.

## 42. Config Example Template
- **Goal**: Provide a documented, PII-free config template for reference.
- **Implementation**:
  - **`config_example.yaml`**: Created with all PII replaced by placeholders, every field commented with description and how to obtain the value.
  - **`config.yaml`**: Removed from git tracking (`git rm --cached`), added to `.gitignore`. File remains locally.
  - **`README.md`**: Setup step now references `cp config_example.yaml config.yaml` instead of an inline YAML block.

## 43. SearXNG URL Configurable
- **Problem**: SearXNG URL was hardcoded in `tools/searxng_search.py` (`http://localhost:8081/search`).
- **Solution**: Added `searxng.url` to `config.yaml` / `config_example.yaml`. `searxng_search.py` reads it from config at runtime via `_get_searxng_url()`, falling back to `localhost:8081` if missing.

## 44. PII Cleanup
- **Goal**: Remove all personally identifiable information from tracked files.
- **Changes**:
  - **`config.yaml`**: Removed from git tracking (already done in #42).
  - **`whatsapp_agent.py`**: Replaced all 10 hardcoded instances of owner name with `owner_name = profile.get('name', 'the owner')` — system prompts now pull the name from config at runtime.
  - **`worklog.md`**: Stripped real WhatsApp number, replaced owner/contact names with `[Owner]` / `[Contact]`.
  - **`plans/unified_yaml_config_plan.md`**: Replaced all real IDs (Telegram chat ID, WhatsApp number, Calendar ID, contact/group IDs) with placeholders.
  - **`plans/style_mimicry_plan.md`**, **`whatsapp_context_awareness_plan.md`**, **`whatsapp_group_autoresponder_plan.md`**, **`whatsapp_take_message_plan.md`**, **`security_hardening_plan.md`**: Replaced all instances of owner/contact names with `[Owner]` / `[Contact]`.
  - **`config_example.yaml`**: Comment referencing owner name replaced with `[Owner]`.
- **Verification**: `git grep` for all known PII terms returns zero results across tracked files.

---
*Last updated: 2026-06-10*
