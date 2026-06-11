# Email Checking & Draft Creation Plan

**Status:** ⬜ Not started

## Goal

Add Gmail integration so the bot can:

1. **Check email** — summarize inbox, list unread, search threads
2. **Draft emails** — compose drafts without sending (human-in-the-loop, matching existing WhatsApp message proposal pattern)
3. **Approve/send drafts** — owner approves via Telegram inline buttons, pushed to Gmail drafts or sent directly

## Provider Choice

**Gmail API** (Google OAuth) — you already have OAuth infra from Calendar. Adding `gmail` scope is one-line change. No new packages needed.

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
          → Owner clicks Send → bot.py calls Gmail API to create draft + optionally send
```

## New Dependencies

None — `google-api-python-client` is already installed. Just a new OAuth scope.

## Database Changes

```sql
CREATE TABLE IF NOT EXISTS email_drafts (
    draft_id       TEXT PRIMARY KEY,
    sender_name    TEXT,          -- display name of who requested (e.g. "via Telegram")
    to_recipients  TEXT,          -- JSON array of email addresses
    cc_recipients  TEXT,          -- JSON array or null
    subject        TEXT,
    body           TEXT,          -- plain text body
    is_html        INTEGER DEFAULT 0,
    gmail_draft_id TEXT,          -- set after pushing to Gmail drafts folder
    status         TEXT DEFAULT 'pending',  -- pending | pushed | sent | cancelled
    created_at     DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

## OAuth Scope Update

In `tools/google_calendar.py` and `setup_auth.py`, add `gmail.modify` scope:

```python
SCOPES = [
    'https://www.googleapis.com/auth/calendar.readonly',
    'https://www.googleapis.com/auth/calendar.events',
    'https://www.googleapis.com/auth/gmail.modify',   # read + compose
]
```

**Important:** Adding a new scope means `token.json` expires and must be re-authed. `setup_auth.py` handles this automatically on next run, or the existing token refresh logic in `get_calendar_service()` will re-prompt.

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
├── get_gmail_service()          # reuse OAuth from google_calendar, same token.json
├── check_inbox(max_results, query) → str   # lists unread with snippet
├── read_email(message_id) → str           # full thread content
├── create_draft(to, cc, subject, body) → str  # saves to DB as pending
├── push_draft(draft_id) → str              # pushes to Gmail drafts folder via API
├── send_draft(draft_id) → str              # sends a Gmail draft by ID
└── mark_read(message_id) → str
```

### Key Design Decisions

- **Reuse existing OAuth** — share the same `token.json` from `google_calendar.py`. No separate auth needed.
- **`check_inbox`** returns formatted summary: sender, subject, snippet, message ID (for follow-up `read_email`)
- **`create_draft`** saves to local DB first (like WhatsApp proposals), returns `[Draft: <id>]`
- **`push_draft`** creates it in Gmail's actual drafts folder (so owner can see it there too)
- **`send_draft`** actually sends it via Gmail API's `users.drafts.send`

## `bot.py` Changes

### New command

```
/email_summary    → quick unread count + top 5
```

### Inline button handler (in `handle_event_proposal`)

```python
elif data.startswith("draft_send_"):
    draft_id = data[11:]
    # fetch from email_drafts, call gmail.push_draft + send_draft
    # update status

elif data.startswith("draft_cancel_"):
    draft_id = data[13:]
    # update status to cancelled
```

### Tag detection (in `send_long_message`)

```python
draft_match = re.search(r'\[Draft:\s*(\w+)\]', chat_response)
if draft_match:
    draft_id = draft_match.group(1)
    # fetch draft details from DB
    # show preview with ✅ Send / ❌ Cancel buttons
    # strip tag from visible text
```

## Edge Cases & Safety

| Concern | Handling |
|---------|----------|
| **Never auto-send** | All email sending goes through draft → approve flow. No direct send. |
| **Sensitive content** | Email body shown in Telegram preview, truncated to ~300 chars if long |
| **OAuth expiry** | Same refresh logic as Calendar. If token is stale, `get_gmail_service()` re-auths via Telegram prompt |
| **Large inboxes** | `check_inbox` capped at 50 results. Use query filters for specificity |
| **Attachments** | Not supported in v1 — LLM instructed to note "bot cannot handle attachments" |
| **HTML vs plain text** | Default plain text. Owner can request HTML if needed later |
| **Rate limits** | Gmail API allows 250 reads + 100 writes/day for free tier. Summaries use `users.messages.list` which is cheap |
| **Wrong recipient** | Draft shows full recipient list before sending — owner approves or cancels |

## Implementation Steps

1. **Update OAuth scopes** — add `gmail.modify` to `google_calendar.py` SCOPES + `setup_auth.py`
2. **Create `tools/gmail.py`** — Gmail API wrapper with the 6 functions above
3. **Add DB table** — `email_drafts` in `whatsapp_server/index.js` DB init (or create a separate migration helper)
4. **Register tools in `core_brain.py`** — add 4 tool definitions to `ADMIN_TOOLS`, add dispatch cases in `execute_tool()`
5. **Add `draft_email` return handling** — detect `[Draft: <id>]` tag in `core_brain.get_llm_response()` (same pattern as `[Proposal: <id>]`)
6. **Add Telegram inline buttons** — `draft_send_` / `draft_cancel_` callbacks in `bot.py`
7. **Add `/email_summary` command** in `bot.py`
8. **Update README** — document new commands and capabilities
9. **Re-auth Gmail** — owner runs `setup_auth.py` once to get new `token.json` with Gmail scope

**Estimated effort:** ~3 files new/modified, ~400 lines of code.

## System Prompt Update

Add to the starter prompt in `core_brain.py`:

> "When the owner asks to email someone, use `draft_email` to compose the email and return the [Draft: <id>] tag. NEVER send emails directly — they must always be reviewed and approved by the owner first."
