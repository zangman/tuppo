import sqlite3
import sys
import types
from datetime import datetime, timedelta

import pytest
import whatsapp_summary as ws

# ── Helpers ─────────────────────────────────────────────────────────


def _now_str():
  """Current time as 'YYYY-MM-DD HH:MM:SS'."""
  return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _recent_str(hours_ago=1):
  """A timestamp hours_ago hours ago as 'YYYY-MM-DD HH:MM:SS'."""
  return (datetime.now() - timedelta(hours=hours_ago)).strftime("%Y-%m-%d %H:%M:%S")


def _old_str(days_ago=30):
  """A timestamp days_ago days ago as 'YYYY-MM-DD HH:MM:SS'."""
  return (datetime.now() - timedelta(days=days_ago)).strftime("%Y-%m-%d %H:%M:%S")


def _patch_db_path(monkeypatch, db_path):
  """Patch the module-level DB_PATH to point to our temp DB."""
  monkeypatch.setattr(ws, "DB_PATH", db_path)


def _insert_messages(db_path, rows):
  """Insert raw message rows into a DB.
    rows = [(message_id, group_id, group_name, sender, text, timestamp), ...]
    """
  conn = sqlite3.connect(db_path)
  cursor = conn.cursor()
  cursor.executemany(
    "INSERT INTO whatsapp_messages (message_id, group_id, group_name, sender, text, timestamp) "
    "VALUES (?, ?, ?, ?, ?, ?)",
    rows,
  )
  conn.commit()
  conn.close()


def _set_bookmark(db_path, chat_id, timestamp):
  """Insert/update a bookmark in chat_status."""
  conn = sqlite3.connect(db_path)
  cursor = conn.cursor()
  cursor.execute(
    "INSERT INTO chat_status (chat_id, last_read_timestamp) VALUES (?, ?) "
    "ON CONFLICT(chat_id) DO UPDATE SET last_read_timestamp = excluded.last_read_timestamp",
    (chat_id, timestamp),
  )
  conn.commit()
  conn.close()


def _get_bookmark(db_path, chat_id):
  """Read the bookmark for a chat."""
  conn = sqlite3.connect(db_path)
  cursor = conn.cursor()
  cursor.execute("SELECT last_read_timestamp FROM chat_status WHERE chat_id = ?", (chat_id,))
  row = cursor.fetchone()
  conn.close()
  return row[0] if row else None


# ── _utc_to_local ───────────────────────────────────────────────────


class TestUtcToLocal:

  def test_utc_to_singapore(self, mock_config):
    # 2025-06-14 01:00 UTC -> 09:00 +08
    result = ws._utc_to_local("2025-06-14 01:00:00")
    assert "09:00:00" in result
    assert "+08" in result

  def test_utc_to_utc(self, monkeypatch):
    fake_config = types.ModuleType("util.config")
    fake_config.load_config = lambda: {"owner": {"timezone": "UTC"}}
    monkeypatch.setitem(sys.modules, "util.config", fake_config)
    fake_util = types.ModuleType("util")
    fake_util.config = fake_config
    monkeypatch.setitem(sys.modules, "util", fake_util)
    monkeypatch.setattr(ws, "config", fake_config)

    result = ws._utc_to_local("2025-06-14 01:00:00")
    assert "01:00:00" in result

  def test_invalid_input_raises(self, mock_config):
    with pytest.raises(ValueError):
      ws._utc_to_local("not-a-date")


# ── _format_time_local ──────────────────────────────────────────────


class TestFormatTimeLocal:

  def test_format_time_singapore(self, mock_config):
    # 01:00 UTC -> 09:00 SGT
    result = ws._format_time_local("2025-06-14 01:00:00")
    assert result == "09:00"

  def test_format_time_invalid_raises(self, mock_config):
    with pytest.raises(ValueError):
      ws._format_time_local("not-a-date")

  def test_format_time_midnight(self, mock_config):
    # 00:00 UTC -> 08:00 SGT
    result = ws._format_time_local("2025-06-14 00:00:00")
    assert result == "08:00"


# ── _resolve_chat ───────────────────────────────────────────────────


class TestResolveChat:

  def test_exact_match(self, tmp_db_path):
    _insert_messages(tmp_db_path, [
      ("m1", "gid1", "Family Group", "Mom", "Hi", _now_str()),
    ])
    conn = sqlite3.connect(tmp_db_path)
    cursor = conn.cursor()
    gid, name = ws._resolve_chat(cursor, "Family Group")
    conn.close()
    assert gid == "gid1"
    assert name == "Family Group"

  def test_partial_match(self, tmp_db_path):
    _insert_messages(tmp_db_path, [
      ("m1", "gid1", "Family Group", "Mom", "Hi", _now_str()),
    ])
    conn = sqlite3.connect(tmp_db_path)
    cursor = conn.cursor()
    gid, name = ws._resolve_chat(cursor, "Family")
    conn.close()
    assert gid == "gid1"
    assert name == "Family Group"

  def test_no_match(self, tmp_db_path):
    conn = sqlite3.connect(tmp_db_path)
    cursor = conn.cursor()
    gid, name = ws._resolve_chat(cursor, "NonExistent")
    conn.close()
    assert gid is None
    assert name is None

  def test_multiple_matches_returns_first(self, tmp_db_path):
    _insert_messages(tmp_db_path, [
      ("m1", "gid1", "Family Group A", "Mom", "Hi", _now_str()),
      ("m2", "gid2", "Family Group B", "Dad", "Hi", _now_str()),
    ])
    conn = sqlite3.connect(tmp_db_path)
    cursor = conn.cursor()
    gid, name = ws._resolve_chat(cursor, "Family Group")
    conn.close()
    assert gid in ("gid1", "gid2")
    assert "Family Group" in name


# ── _list_active_chats ──────────────────────────────────────────────


class TestListActiveChats:

  def test_lists_chats(self, populated_db):
    conn = sqlite3.connect(populated_db)
    cursor = conn.cursor()
    result = ws._list_active_chats(cursor)
    conn.close()
    assert "Family Group" in result
    assert "Work Team" in result

  def test_no_active_chats(self, tmp_db_path):
    conn = sqlite3.connect(tmp_db_path)
    cursor = conn.cursor()
    result = ws._list_active_chats(cursor)
    conn.close()
    assert "No active WhatsApp chats" in result

  def test_excludes_old_chats(self, populated_db, mock_config):
    conn = sqlite3.connect(populated_db)
    cursor = conn.cursor()
    result = ws._list_active_chats(cursor)
    conn.close()
    # "Old Chat" has messages from 30 days ago, beyond 7 days
    assert "Old Chat" not in result


# ── _not_found_response ─────────────────────────────────────────────


class TestNotFoundResponse:

  def test_includes_active_chats(self, populated_db):
    conn = sqlite3.connect(populated_db)
    cursor = conn.cursor()
    result = ws._not_found_response("NoMatch", cursor)
    conn.close()
    assert "No chats found matching 'NoMatch'" in result
    assert "Active WhatsApp chats" in result


# ── get_new_messages ────────────────────────────────────────────────


class TestGetNewMessages:

  def test_no_chat_query_lists_chats(self, populated_db, monkeypatch, mock_config):
    _patch_db_path(monkeypatch, populated_db)
    result = ws.get_new_messages()
    assert "Active WhatsApp chats" in result

  def test_chat_not_found(self, populated_db, monkeypatch, mock_config):
    _patch_db_path(monkeypatch, populated_db)
    result = ws.get_new_messages("DefinitelyNotARealChat")
    assert "No chats found matching" in result

  def test_no_new_messages(self, populated_db, monkeypatch, mock_config):
    _patch_db_path(monkeypatch, populated_db)
    # Set bookmark past all messages
    _set_bookmark(populated_db, "gid_family", _now_str())
    result = ws.get_new_messages("Family")
    assert "no new unread messages" in result

  def test_new_messages_returned(self, populated_db, monkeypatch, mock_config):
    _patch_db_path(monkeypatch, populated_db)
    # Set bookmark before all messages
    _set_bookmark(populated_db, "gid_family", _old_str(days_ago=30))
    result = ws.get_new_messages("Family")
    assert "SUMMARY DATA" in result
    assert "Mom" in result
    assert "Dad" in result

  def test_first_time_read_no_bookmark(self, populated_db, monkeypatch, mock_config):
    _patch_db_path(monkeypatch, populated_db)
    # No bookmark for gid_work; MIN timestamp becomes bookmark, query uses >
    # so the oldest message (Alice) is excluded, Bob is returned
    result = ws.get_new_messages("Work")
    assert "SUMMARY DATA" in result
    assert "Bob" in result

  def test_bookmark_advances(self, populated_db, monkeypatch, mock_config):
    _patch_db_path(monkeypatch, populated_db)
    _set_bookmark(populated_db, "gid_family", _old_str(days_ago=30))
    ws.get_new_messages("Family")
    bookmark = _get_bookmark(populated_db, "gid_family")
    # Should be the latest message timestamp for Family Group
    assert bookmark is not None
    assert bookmark > _old_str(days_ago=30)

  def test_db_not_exists(self, monkeypatch, mock_config):
    _patch_db_path(monkeypatch, "/tmp/nonexistent_whatsapp_12345.db")
    result = ws.get_new_messages()
    assert "does not exist" in result

  def test_no_messages_returns_no_new(self, tmp_db_path, monkeypatch, mock_config):
    """Chat exists but has no messages after bookmark."""
    _insert_messages(tmp_db_path, [
      ("m1", "gid1", "Test Chat", "Alice", "Hello", _recent_str(hours_ago=2)),
    ])
    _set_bookmark(tmp_db_path, "gid1", _now_str())
    _patch_db_path(monkeypatch, tmp_db_path)
    result = ws.get_new_messages("Test Chat")
    assert "no new unread messages" in result


# ── get_chat_history ────────────────────────────────────────────────


class TestGetChatHistory:

  def test_chat_not_found(self, populated_db, monkeypatch, mock_config):
    _patch_db_path(monkeypatch, populated_db)
    result = ws.get_chat_history("NoRealChat")
    assert "No chats found matching" in result

  def test_db_not_exists(self, monkeypatch, mock_config):
    _patch_db_path(monkeypatch, "/tmp/nonexistent_whatsapp_67890.db")
    result = ws.get_chat_history("AnyChat")
    assert "does not exist" in result

  def test_fetches_messages(self, tmp_db_path, monkeypatch, mock_config):
    _patch_db_path(monkeypatch, tmp_db_path)
    _insert_messages(tmp_db_path, [
      ("m1", "gid1", "Test Chat", "Alice", "Hello world", _recent_str(hours_ago=1)),
      ("m2", "gid1", "Test Chat", "Bob", "Hey there", _recent_str(hours_ago=0.5)),
    ])
    result = ws.get_chat_history("Test Chat", timeframe_hours=24)
    assert "Alice" in result
    assert "Bob" in result

  def test_search_text_filter(self, tmp_db_path, monkeypatch, mock_config):
    _patch_db_path(monkeypatch, tmp_db_path)
    _insert_messages(tmp_db_path, [
      ("m1", "gid1", "Test Chat", "Alice", "Hello world", _recent_str(hours_ago=1)),
      ("m2", "gid1", "Test Chat", "Bob", "Goodbye world", _recent_str(hours_ago=0.75)),
      ("m3", "gid1", "Test Chat", "Charlie", "No match here", _recent_str(hours_ago=0.5)),
    ])
    result = ws.get_chat_history("Test Chat", timeframe_hours=24, search_text="world")
    assert "Alice" in result
    assert "Bob" in result
    assert "Charlie" not in result
    assert "No match here" not in result

  def test_no_messages_in_range(self, tmp_db_path, monkeypatch, mock_config):
    _patch_db_path(monkeypatch, tmp_db_path)
    _insert_messages(tmp_db_path, [
      ("m1", "gid1", "Test Chat", "Alice", "Old message", _old_str(days_ago=30)),
    ])
    result = ws.get_chat_history("Test Chat", timeframe_hours=1)
    assert "no messages" in result

  def test_header_format(self, tmp_db_path, monkeypatch, mock_config):
    _patch_db_path(monkeypatch, tmp_db_path)
    _insert_messages(tmp_db_path, [
      ("m1", "gid1", "Test Chat", "Alice", "Hi", _recent_str(hours_ago=1)),
    ])
    result = ws.get_chat_history("Test Chat", timeframe_hours=48)
    assert "Test Chat" in result
    assert "48h" in result

  def test_header_with_search(self, tmp_db_path, monkeypatch, mock_config):
    _patch_db_path(monkeypatch, tmp_db_path)
    _insert_messages(tmp_db_path, [
      ("m1", "gid1", "Test Chat", "Alice", "Hello test", _recent_str(hours_ago=1)),
    ])
    result = ws.get_chat_history("Test Chat", timeframe_hours=48, search_text="test")
    assert "filtered by 'test'" in result


# ── Truncation ──────────────────────────────────────────────────────


class TestTruncation:

  def test_new_messages_truncation(self, tmp_db_path, monkeypatch, mock_config):
    """When output exceeds _MAX_OUTPUT_CHARS, only first N messages are shown."""
    _patch_db_path(monkeypatch, tmp_db_path)
    # Insert many long messages to exceed 3500 chars
    rows = []
    for i in range(100):
      ts = _recent_str(hours_ago=(100 - i) / 60)
      rows.append((f"m{i}", "gid1", "Big Chat", f"Sender{i}", "X" * 100, ts))
    _insert_messages(tmp_db_path, rows)
    _set_bookmark(tmp_db_path, "gid1", _old_str(days_ago=30))

    result = ws.get_new_messages("Big Chat")
    assert len(result) <= ws._MAX_OUTPUT_CHARS + 50  # small tolerance for header
    assert "Truncated" in result

  def test_chat_history_truncation(self, tmp_db_path, monkeypatch, mock_config):
    """When history output exceeds _MAX_OUTPUT_CHARS, it is truncated."""
    _patch_db_path(monkeypatch, tmp_db_path)
    rows = []
    for i in range(100):
      ts = _recent_str(hours_ago=(100 - i) / 60)
      rows.append((f"m{i}", "gid1", "Big Chat", f"Sender{i}", "Y" * 100, ts))
    _insert_messages(tmp_db_path, rows)

    result = ws.get_chat_history("Big Chat", timeframe_hours=48)
    assert len(result) <= ws._MAX_OUTPUT_CHARS + 50
    assert "Truncated" in result


# ── Edge cases ──────────────────────────────────────────────────────


class TestEdgeCases:

  def test_empty_text_message(self, tmp_db_path, monkeypatch, mock_config):
    """Messages with empty text are handled."""
    _patch_db_path(monkeypatch, tmp_db_path)
    _insert_messages(tmp_db_path, [
      ("m1", "gid1", "Test Chat", "Alice", "", _recent_str(hours_ago=1)),
    ])
    _set_bookmark(tmp_db_path, "gid1", _old_str(days_ago=30))
    result = ws.get_new_messages("Test Chat")
    assert "Alice" in result
    assert "SUMMARY DATA" in result

  def test_special_characters_in_text(self, tmp_db_path, monkeypatch, mock_config):
    """Messages with special characters are handled."""
    _patch_db_path(monkeypatch, tmp_db_path)
    _insert_messages(tmp_db_path, [
      ("m1", "gid1", "Test Chat", "Alice", "Hello! @#$%^&*() \u00f1 \u4e2d\u6587 \U0001f389", _recent_str(hours_ago=1)),
    ])
    _set_bookmark(tmp_db_path, "gid1", _old_str(days_ago=30))
    result = ws.get_new_messages("Test Chat")
    assert "\u00f1" in result
    assert "\U0001f389" in result

  def test_multiple_bookmark_updates(self, tmp_db_path, monkeypatch, mock_config):
    """Calling get_new_messages twice advances the bookmark correctly."""
    _patch_db_path(monkeypatch, tmp_db_path)
    t1 = _recent_str(hours_ago=3)
    t2 = _recent_str(hours_ago=2)
    t3 = _recent_str(hours_ago=1)
    _insert_messages(tmp_db_path, [
      ("m1", "gid1", "Test Chat", "Alice", "First", t1),
      ("m2", "gid1", "Test Chat", "Bob", "Second", t2),
      ("m3", "gid1", "Test Chat", "Charlie", "Third", t3),
    ])
    _set_bookmark(tmp_db_path, "gid1", _old_str(days_ago=30))

    # First call: should get all 3, bookmark advances to t3
    result1 = ws.get_new_messages("Test Chat")
    assert "First" in result1
    assert "Third" in result1

    # Second call: no new messages
    result2 = ws.get_new_messages("Test Chat")
    assert "no new unread messages" in result2

  def test_first_time_with_few_messages(self, tmp_db_path, monkeypatch, mock_config):
    """When fewer than 1000 messages and no bookmark, starts from oldest."""
    _patch_db_path(monkeypatch, tmp_db_path)
    t1 = _recent_str(hours_ago=3)
    t2 = _recent_str(hours_ago=2)
    t3 = _recent_str(hours_ago=1)
    _insert_messages(tmp_db_path, [
      ("m1", "gid1", "Test Chat", "Alice", "First", t1),
      ("m2", "gid1", "Test Chat", "Bob", "Second", t2),
      ("m3", "gid1", "Test Chat", "Charlie", "Third", t3),
    ])
    result = ws.get_new_messages("Test Chat")
    # Bookmark is set to MIN timestamp; query uses > so first msg is excluded
    assert "Second" in result
    assert "Third" in result
