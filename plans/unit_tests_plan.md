# Unit Tests Plan

## New Files

| File | ~Tests | Focus |
|---|---|---|
| `util/tests/__init__.py` | — | empty |
| `util/tests/conftest.py` | 2 fixtures | shared DB schemas |
| `util/tests/test_scheduling.py` | ~18 | pure helpers + DB handlers + mocked confirmation |
| `util/tests/test_db_tools.py` | ~13 | all 5 DB handlers with in-memory SQLite |
| `core_brain/tests/__init__.py` | — | empty |
| `core_brain/tests/test_core_brain.py` | ~16 | parsing, RBAC, formatting, reasoning, token limit |

**Total: ~47 new tests**, all using in-memory SQLite or pure function calls — no external dependencies needed.

---

## 1. `util/tests/conftest.py`

Shared fixtures for in-memory SQLite schemas.

```python
import sqlite3
import pytest

@pytest.fixture
def sched_db_path(tmp_path):
  """In-memory DB with scheduled_tasks table."""
  path = str(tmp_path / "test.db")
  conn = sqlite3.connect(path)
  conn.execute("""CREATE TABLE scheduled_tasks (
      task_id TEXT, owner_id TEXT, execution_time TEXT,
      action_type TEXT, action_params TEXT, cron_expression TEXT, status TEXT
  )""")
  conn.commit()
  conn.close()
  return path

@pytest.fixture
def wa_db_path(tmp_path):
  """In-memory DB with WhatsApp tables."""
  path = str(tmp_path / "wa.db")
  conn = sqlite3.connect(path)
  conn.execute("""CREATE TABLE contacts (
      chat_id TEXT, display_name TEXT, last_seen TEXT
  )""")
  conn.execute("""CREATE TABLE whatsapp_proposals (
      proposal_id TEXT, chat_id TEXT, recipient_name TEXT,
      message_text TEXT, status TEXT
  )""")
  conn.execute("""CREATE TABLE messages_for_owner (
      id INTEGER PRIMARY KEY, sender_name TEXT, sender_id TEXT,
      chat_name TEXT, chat_id TEXT, message_text TEXT,
      timestamp TEXT, read_status TEXT
  )""")
  conn.commit()
  conn.close()
  return path
```

---

## 2. `util/tests/test_scheduling.py`

### Pure helpers (no DB, no network)

**`TestValidateScheduleArgs`**
- `test_missing_execution_time` — empty args returns error
- `test_recurring_missing_cron` — `is_recurring=True` without cron returns error
- `test_valid_args` — returns `(execution_time, cron, None)`
- `test_valid_args_no_cron` — non-recurring, cron=None is fine

**`TestNormalizeExecutionTime`**
- `test_naive_time_localized_to_sg` — naive → SG → UTC
- `test_already_utc` — tz-aware UTC passes through
- `test_invalid_format` — garbage string returns error

**`TestFlattenScheduleParams`**
- `test_strips_execution_time_and_cron` — both keys removed
- `test_keeps_other_keys` — `message_text`, `recipients` preserved
- `test_empty_args` — returns `{}`

### DB helpers (in-memory SQLite via `sched_db_path`)

**`TestInsertScheduledTask`**
- `test_inserts_row` — insert, query, assert row exists with correct values

**`TestHandleListScheduledTasks`**
- `test_empty_table` — returns "No pending scheduled tasks found."
- `test_lists_pending_tasks` — seed 2 rows, assert formatted output
- `test_excludes_cancelled` — seed 1 pending + 1 cancelled, only 1 shown

**`TestHandleCancelScheduledTask`**
- `test_cancels_task` — insert task, cancel, verify status = 'cancelled'

### Handler with mocking

**`TestHandleScheduleTask`**
- `test_returns_none_for_unknown_tool` — non-scheduling tool → None
- `test_valid_schedule` — mock `send_scheduling_confirmation`, assert result string starts with "Task scheduled successfully"
- `test_validation_error_propagated` — missing execution_time → error string
- `test_parse_error_propagated` — bad time format → error string

**`TestSendSchedulingConfirmation`**
- `test_sends_notification` — mock `requests.post` and `util.config.load_config`, assert post called with correct payload
- `test_returns_early_no_owner_id` — config with no owner → no post call

---

## 3. `util/tests/test_db_tools.py`

All use in-memory SQLite via `wa_db_path` fixture.

**`TestHandleFindWhatsappChat`**
- `test_finds_exact_match` — seed "Alice", search "Alice"
- `test_finds_partial_match` — seed "Alice Smith", search "Alice"
- `test_no_matches` — empty table
- `test_multiple_matches` — seed 2 contacts, both in output

**`TestHandleProposeWhatsappMessage`**
- `test_returns_proposal_id` — assert `[Proposal: <8chars>]`
- `test_row_inserted` — query DB after call, assert row exists

**`TestHandleCountPendingMessages`**
- `test_zero_messages` — empty table → "0 pending"
- `test_counts_unread_only` — seed 2 unread + 1 read → "2 pending"

**`TestHandleGetPendingMessages`**
- `test_no_messages` — empty table → "No pending messages"
- `test_returns_messages` — seed 1 message, assert formatted output includes sender/message text

**`TestHandleClearMessages`**
- `test_clear_all` — mode='all', seed 3 unread → "Cleared 3"
- `test_clear_by_ids` — mode='ids', seed 3, clear 1 → "Cleared 1"
- `test_clear_empty_ids` — mode='ids', ids=[] → "Cleared 0"

---

## 4. `core_brain/tests/test_core_brain.py`

**`TestParseToolCall`**
- `test_parses_tool_call` — feed dict, assert `(id, name, parsed_args)`
- `test_parses_nested_json_args` — args with nested objects

**`TestGetAllowedTools`**
- `test_tg_prefix_returns_admin` — `tg_123` → `ADMIN_TOOLS`
- `test_wa_prefix_returns_whatsapp` — `wa_456` → `WHATSAPP_TOOLS`
- `test_other_returns_public` — `user_789` → `PUBLIC_TOOLS`

**`TestValidateToolAccess`**
- `test_allowed_tool` — `calc` in `PUBLIC_TOOLS` → True
- `test_forbidden_tool` — admin tool in `PUBLIC_TOOLS` → False

**`TestFormatMsg`**
- `test_returns_tool_message` — assert dict shape

**`TestLogResult`**
- `test_short_content` — no truncation
- `test_long_content_truncated` — >500 chars → `...` appended

**`TestToolReturn`**
- `test_returns_formatted_msg` — calls `_log_result` + `format_msg`

**`TestStripReasoning`**
- `test_removes_reasoning_content` — message with `reasoning_content` → stripped
- `test_preserves_other_keys` — `role`, `content` kept

**`TestLimitTokens`**
- `test_small_messages_unchanged` — under limit → same list
- `test_evicts_oldest_blocks` — over limit → trimmed
- `test_always_keeps_system_prompt` — index 0 never evicted
- `test_evicts_complete_exchanges` — assistant tool_call + tool result evicted together

---

## Open Questions

1. **`send_scheduling_confirmation`** — mock `requests.post` and `util.config.load_config`, or skip entirely (hard to test without real config)?
2. **Async dispatchers** in `core_brain.py` (`_handle_basic_tools`, etc.) — test with mocked external modules, or skip (thin wrappers)?
3. **Naming convention** — existing tests use `TestClassName::test_method_name`. Follow that style?
