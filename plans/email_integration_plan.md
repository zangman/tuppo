# Email Checking & Draft Creation Plan

**Status:** ⬜ Not started

## Goal

Add Gmail integration so the bot can:

1. **Check email** — summarize inbox, list unread, search threads
2. **Draft emails** — compose drafts without sending (human-in-the-loop, matching existing WhatsApp message proposal pattern)
3. **Approve/send drafts** — owner approves via Telegram inline buttons, sent directly through Gmail API

## Provider Choice

**Gmail API** (Google OAuth) — shares the existing OAuth infrastructure from Calendar. Adding `gmail` scope is a one-line change per file. No new packages needed.

## Architecture

```
┌───────────┐     ┌──────────────┐     ┌──────────────────┐
│ Telegram  │────▶│  bot.py      │────▶│  core_brain.py   │
└───────────┘     └──────────────┘     │  (tool dispatch)  │
                                       └────────┬───────────┘
                                                │
                                        ┌───────▼──────────┐
                                        │ tools/gmail.py    │
                                        │ (Gmail API client)│
                                        └───────┬───────────┘
                                                │ OAuth (shared token.json)
                                        ┌───────▼──────────┐
                                        │  Google API       │
                                        └──────────────────┘
```

**Flow for sending:**

```
User asks bot to email someone
  → LLM calls draft_email tool
    → Saved to email_drafts table (pending)
      → LLM returns [Draft: <id>] tag
        → bot.py detects tag, shows inline buttons: ✅ Send / ❌ Cancel
          → Owner clicks Send → bot.py calls users.drafts.send (single API call)
```

## Dependencies

None — `google-api-python-client` and `beautifulsoup4` are already in `requirements.txt`. Just need a new OAuth scope.

## Database Changes

```sql
CREATE TABLE IF NOT EXISTS email_drafts (
    draft_id          TEXT PRIMARY KEY,
    requester_session TEXT,          -- e.g. "tg_8447979869" (session_id from core_brain)
    to_recipients     TEXT,          -- JSON array of email addresses
    cc_recipients     TEXT,          -- JSON array or null
    subject           TEXT,
    body              TEXT,          -- plain text body
    is_html           INTEGER DEFAULT 0,
    gmail_draft_id    TEXT,          -- Gmail internal draft ID (set on send)
    status            TEXT DEFAULT 'pending',  -- pending | sent | cancelled
    created_at        DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

Table is created in `tools/gmail.py` on first run (Python-side only, no Node.js involvement).

## OAuth Scope Update

Add `gmail.modify` to both files:

**`tools/google_calendar.py`:**
```python
SCOPES = [
    'https://www.googleapis.com/auth/calendar.readonly',
    'https://www.googleapis.com/auth/calendar.events',
    'https://www.googleapis.com/auth/gmail.modify',   # read + compose
]
```

**`setup_auth.py`:**
```python
SCOPES = [
    'https://www.googleapis.com/auth/calendar.readonly',
    'https://www.googleapis.com/auth/calendar.events',
    'https://www.googleapis.com/auth/gmail.modify',
]
```

**Important:** Adding a new scope invalidates the existing `token.json`. The owner must re-run `setup_auth.py` once to get a fresh token with the expanded scope.

## Tool Definitions (ADMIN_TOOLS only)

### 1. `check_email_inbox`

```json
{
  "name": "check_email_inbox",
  "description": "Summarize unread emails in the owner's inbox. Optionally filter by sender, recipient, or search query.",
  "parameters": {
    "type": "object",
    "properties": {
      "max_results": {
        "type": "integer",
        "description": "Max emails to show (default 10, max 50)",
        "default": 10
      },
      "query": {
        "type": "string",
        "description": "Gmail search query (e.g. 'from:boss@company.com', 'is:unread has:attachment')"
      }
    }
  }
}
```

### 2. `read_email`

```json
{
  "name": "read_email",
  "description": "Read the full content of a specific email by its Gmail message ID.",
  "parameters": {
    "type": "object",
    "properties": {
      "message_id": {
        "type": "string",
        "description": "Gmail message ID"
      }
    },
    "required": ["message_id"]
  }
}
```

### 3. `draft_email`

```json
{
  "name": "draft_email",
  "description": "Create a draft email for the owner to review before sending. After calling, output ONLY the returned [Draft: <id>] tag.",
  "parameters": {
    "type": "object",
    "properties": {
      "to": {
        "type": "array",
        "items": { "type": "string" },
        "description": "Recipient email addresses"
      },
      "cc": {
        "type": "array",
        "items": { "type": "string" },
        "description": "CC email addresses (optional)"
      },
      "subject": {
        "type": "string",
        "description": "Email subject line"
      },
      "body": {
        "type": "string",
        "description": "Email body (plain text)"
      }
    },
    "required": ["to", "subject", "body"]
  }
}
```

### 4. `mark_email_read`

```json
{
  "name": "mark_email_read",
  "description": "Mark a specific email as read.",
  "parameters": {
    "type": "object",
    "properties": {
      "message_id": {
        "type": "string",
        "description": "Gmail message ID"
      }
    },
    "required": ["message_id"]
  }
}
```

## Module: `tools/gmail.py`

```
gmail.py
├── _ensure_table()                # create email_drafts table if missing
├── get_gmail_service()            # reuse OAuth from google_calendar, same token.json
├── check_inbox(max_results, query) → str   # lists unread with snippet
├── read_email(message_id) → str           # full thread content, HTML stripped
├── create_draft(session_id, to, cc, subject, body) → str  # saves to DB as pending, returns [Draft: <id>]
├── get_draft(draft_id) → str               # returns draft details (for re-reading before approval)
├── send_draft(draft_id) → str              # creates + sends via users.drafts.send (single API call)
├── mark_read(message_id) → str
├── _utc_to_local(utc_str) → str            # convert timestamps to owner's local TZ
└── _format_time_local(ts) → str            # extract HH:MM in local TZ
```

### Key Design Decisions

- **Reuse existing OAuth** — share the same `token.json` from `google_calendar.py`. No separate auth needed.
- **`check_inbox`** uses `users.messages.list` with `format='metadata'` and `metadataHeaders=['subject', 'from', 'date']` to avoid full-body fetches. Returns formatted summary: sender, subject, snippet, message ID (for follow-up `read_email`).
- **`read_email`** strips HTML using `beautifulsoup4` (already in `requirements.txt`). Returns plain text only.
- **`create_draft`** saves to local DB first (like WhatsApp proposals), returns `[Draft: <id>]`. Does NOT call Gmail API.
- **`send_draft`** creates the draft in Gmail and sends it in a single API call via `users.drafts.send`. No intermediate "push to drafts folder" step.
- **Timezone conversion** uses the same pattern as `whatsapp_summary.py` — reads owner's timezone from config.yaml, converts all timestamps to local time before returning to the LLM.
- **Error handling** — if Gmail API is down, rate-limited, or token expired, each function returns a clear error string the LLM can relay to the user (e.g., "Gmail API error: 403 Token expired. Please re-auth by running setup_auth.py.").

## `bot.py` Changes

### New command

```
/email_summary    → quick unread count + top 5
```

### Tag detection and inline buttons (in `send_long_message`)

```python
draft_match = re.search(r'\[Draft:\s*(\w+)\]', chat_response)
if draft_match:
    draft_id = draft_match.group(1)
    # Strip the tag from the visible text
    chat_response = re.sub(r'\s*\[Draft:\s*\w+\]', '', chat_response).strip()

    # Fetch draft details from DB
    conn = sqlite3.connect(os.path.join(ROOT_DIR, 'whatsapp.db'), timeout=10.0)
    cursor = conn.cursor()
    cursor.execute("SELECT to_recipients, subject, body FROM email_drafts WHERE draft_id = ?", (draft_id,))
    row = cursor.fetchone()
    conn.close()

    if row:
        to_list, subject, body = row
        to_display = ', '.join(json.loads(to_list))
        # Truncate body preview to ~300 chars
        body_preview = (body[:297] + '...') if len(body) > 300 else body
        chat_response = (
            f"{chat_response}\n\n"
            f"{'—'}\n"
            f"📨 Pending Email Draft\n"
            f"To: {to_display}\n"
            f"Subject: {subject}\n"
            f"Body:\n> {body_preview}"
        )

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Send", callback_data=f"draft_send_{draft_id}"),
         InlineKeyboardButton("❌ Cancel", callback_data=f"draft_cancel_{draft_id}")]
    ])
    reply_markup = keyboard
```

### Inline button handler (in `handle_event_proposal`)

```python
elif data.startswith("draft_send_"):
    draft_id = data[11:]
    result = gmail.send_draft(draft_id)
    await query.edit_message_text(text=result, reply_markup=None)

elif data.startswith("draft_cancel_"):
    draft_id = data[13:]
    conn = sqlite3.connect(os.path.join(ROOT_DIR, 'whatsapp.db'), timeout=10.0)
    cursor = conn.cursor()
    cursor.execute("UPDATE email_drafts SET status = 'cancelled' WHERE draft_id = ?", (draft_id,))
    conn.commit()
    conn.close()
    await query.edit_message_text(text="❌ Email draft cancelled.", reply_markup=None)
```

## Files Affected (7+)

| File | Change |
|------|--------|
| `tools/gmail.py` | **New** — Gmail API wrapper (~250 lines) |
| `tools/google_calendar.py` | Add `gmail.modify` to SCOPES |
| `setup_auth.py` | Add `gmail.modify` to SCOPES |
| `core_brain.py` | Add `import tools.gmail as gmail`, add 4 tool defs to ADMIN_TOOLS, add dispatch cases in `execute_tool()` |
| `bot.py` | Add `draft_send_`/`draft_cancel_` callbacks, add `[Draft: <id>]` tag detection in `send_long_message()`, add `/email_summary` command |
| `README.md` | Document new commands and capabilities |
| `plans/email_integration_plan.md` | This plan |

## Edge Cases & Safety

| Concern | Handling |
|---------|----------|
| **Never auto-send** | All email sending goes through draft → approve flow. No direct send. |
| **Sensitive content** | Email body shown in Telegram preview, truncated to ~300 chars if long |
| **OAuth expiry** | Same refresh logic as Calendar. If token is stale, `get_gmail_service()` re-auths via Telegram prompt. Error message returned to LLM for user relay. |
| **Large inboxes** | `check_inbox` capped at 50 results. Use query filters for specificity. |
| **Attachments** | Not supported in v1 — LLM instructed to note "bot cannot handle attachments" |
| **HTML vs plain text** | Default plain text. `read_email` strips HTML from incoming messages using BeautifulSoup. Owner can request HTML if needed later. |
| **Rate limits** | Gmail API allows 250 reads + 100 writes/day for free tier. `check_inbox` uses `format='metadata'` which is lightweight. |
| **Wrong recipient** | Draft shows full recipient list before sending — owner approves or cancels |
| **API downtime / errors** | All functions return descriptive error strings. LLM relays to user. No silent failures. |
| **UTC vs local time** | All timestamps converted to owner's local timezone before returning to LLM (same pattern as `whatsapp_summary.py`) |

## Implementation Steps

1. **Update OAuth scopes** — add `gmail.modify` to both `tools/google_calendar.py` SCOPES and `setup_auth.py` SCOPES
2. **Create `tools/gmail.py`** — Gmail API wrapper with all functions listed above, including `_ensure_table()` for DB init, timezone helpers, and error handling
3. **Add import in `core_brain.py`** — `import tools.gmail as gmail` at the top
4. **Register tools in `core_brain.py`** — add 4 tool definitions to `ADMIN_TOOLS`, add dispatch cases in `execute_tool()`
5. **Add Telegram inline buttons and tag detection in `bot.py`** — detect `[Draft: <id>]` in `send_long_message()`, handle `draft_send_`/`draft_cancel_` callbacks in `handle_event_proposal`
6. **Add `/email_summary` command** in `bot.py`
7. **Update README** — document new commands and capabilities
8. **Re-auth Gmail** — owner runs `setup_auth.py` once to get new `token.json` with Gmail scope

**Estimated effort:** 7+ files, ~400 lines of code.

## System Prompt Update

Add to the starter prompt in `core_brain.py`:

> "When the owner asks to email someone, use `draft_email` to compose the email and return the [Draft: <id>] tag. NEVER send emails directly — they must always be reviewed and approved by the owner first. When showing email timestamps, convert them to the owner's local timezone (Asia/Singapore)."
