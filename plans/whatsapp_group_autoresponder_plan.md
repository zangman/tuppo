# Plan: WhatsApp Group Autoresponder — Option 1 (Direct Mention Response)

## Objective
Respond in WhatsApp groups only when the owner is explicitly @mentioned by a group member.

## Technical Details

**Detection** — `msg.getMentions()` returns an array of Contact objects for everyone mentioned in a message. Each contact has an `id` (e.g., `{user: "1234567890", server: "c.us"}`). We compare this against the owner's WhatsApp ID.

**Owner ID Resolution** — We need to know the owner's WhatsApp ID to match against mentions. Two approaches:
- **Manual**: Add `owner_whatsapp_id` to `owner_profile.json` (e.g., `"18123456789"`)
- **Auto-discover**: On first message from the owner's own number (self-chat or group), auto-detect and store it

## Changes Required

### 1. `owner_profile.json` — Owner WhatsApp ID
- Add `"owner_whatsapp_id": "<phone without + or country code>"` for mention matching

### 2. `whatsapp_server/index.js` — Mention Detection
In `message_create`, for group chats:
- Call `msg.getMentions()` to get mentioned users
- Check if any mention matches the owner's WhatsApp ID
- If matched: forward the message to the Python agent webhook (same as private chats)
- Skip the owner's own messages to avoid self-response

### 3. `whatsapp_server/index.js` — Group Contact Sync
- On every group message, upsert the **group itself** into the `contacts` table (group_name → group chatId)
- This makes groups discoverable by name via `find_whatsapp_chat`
- **Do not** upsert individual group members — they aren't actionable message targets and would pollute the table
- People you want to message individually are already in contacts from their private DMs

### 4. `autoresponder_config.json` — Per-Group Allowlist
- Add `"allowed_groups": ["<groupId1>", "<groupId2>"]` to control which groups trigger autoresponse
- Groups not in the list are silently ignored (messages logged but no autoresponse)

### 5. `whatsapp_agent.py` — Group Session Isolation
- Session ID format: `wa_group_<groupId>` so each group has its own conversation history
- System prompt adjusted for group context (e.g., "you're responding in a group chat, be concise, don't over-explain")
- Loop prevention adapted for groups (rate limit per sender, not per chat)

### 6. `whatsapp_agent.py` — Response Routing
- No change needed — `sendMessage` to a group chatId posts in the group (same as private chats)

### 7. `bot.py` — Owner Controls (Telegram)
- `/wa_groups` — list configured allowed groups with names
- `/wa_group_add <group_name>` — add a group to the allowlist (uses `find_whatsapp_chat` to resolve)
- `/wa_group_remove <group_name>` — remove from allowlist

## Safety Guardrails
- **Per-sender rate limit**: Max 2 responses per sender per 60s (stricter than private chats to avoid group spam)
- **Group size cap**: Skip autoresponse in groups with >100 members (too noisy, high risk of awkward public bot replies)
- **Silent fallback**: If the LLM can't form a useful answer, stay silent (no fallback message in groups)

## User Flow
1. Group member: *"@[Owner] are you free Saturday evening?"*
2. WhatsApp server detects mention → forwards to agent
3. Agent checks: group is allowlisted, sender not rate-limited, LLM can answer from calendar
4. Bot replies in group: *"he's free after 6pm sat, want me to propose a time?"*

---

## Other Brainstormed Options (Not Implemented)

### Option 2: Questions *About* the Owner
Detect questions where the owner is the subject — "Is [Owner] coming?" "[Owner] free this weekend?"
- **Pro**: Natural, helpful, owner would want answered
- **Con**: NLP-heavy to distinguish "[Owner] is the best" (no response) from "Is [Owner] free?" (respond)

### Option 3: Scheduling Coordination
When someone proposes a plan involving the owner — "Let's grab food Saturday at 7"
- **Pro**: High-value use case, leverages calendar tools
- **Con**: Hard to detect without knowing group context (plans group vs. meme group)

### Option 4: Explicit Command Prefix
People use a prefix to intentionally trigger the bot — "!ask [Owner], can he make it Friday?"
- **Pro**: Zero false positives, opt-in
- **Con**: Requires behavior change from group members; feels clunky

### Option 5: "Note for [Owner]" Capture
When someone says "[Owner], don't forget about X" or "tell [Owner] to call me back" — bot acknowledges in-group and forwards a summary to the owner on Telegram
- **Pro**: Useful, non-intrusive, doesn't even need to reply in-group for forwarding
- **Con**: Mention-dependent

### Option 6: Per-Group Configuration (General)
Different rules per group — e.g., respond to mentions in family group, respond to scheduling in work group, stay silent in meme group
- **Pro**: Flexible, context-aware
- **Con**: Requires setup/maintenance per group

*Last updated: 2026-05-30*
