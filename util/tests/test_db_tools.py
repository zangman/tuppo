"""Tests for util/db_tools.py."""

import sqlite3

import pytest

from util import db_tools

# ── Helpers ───────────────────────────────────────────────────────────


def _insert_contacts(db_path, rows):
  """Insert rows into contacts table.
    rows = [(chat_id, display_name, last_seen), ...]
    """
  conn = sqlite3.connect(db_path)
  cursor = conn.cursor()
  cursor.executemany(
    "INSERT INTO contacts (chat_id, display_name, last_seen) VALUES (?, ?, ?)",
    rows,
  )
  conn.commit()
  conn.close()


def _insert_messages(db_path, rows):
  """Insert rows into messages_for_owner table.
    rows = [(sender_name, sender_id, chat_name, chat_id, message_text, timestamp, read_status), ...]
    """
  conn = sqlite3.connect(db_path)
  cursor = conn.cursor()
  cursor.executemany(
    "INSERT INTO messages_for_owner (sender_name, sender_id, chat_name, chat_id, message_text, timestamp, read_status) "
    "VALUES (?, ?, ?, ?, ?, ?, ?)",
    rows,
  )
  conn.commit()
  conn.close()


# ── Fixture ───────────────────────────────────────────────────────────


@pytest.fixture
def db_tools_db_path(tmp_path):
  """Create a temp SQLite DB with the db_tools schema."""
  db_path = tmp_path / "db_tools.db"
  conn = sqlite3.connect(str(db_path))
  cursor = conn.cursor()
  cursor.execute("CREATE TABLE contacts ("
                 "chat_id TEXT, "
                 "display_name TEXT, "
                 "last_seen DATETIME"
                 ")")
  cursor.execute("CREATE TABLE whatsapp_proposals ("
                 "proposal_id TEXT, "
                 "chat_id TEXT, "
                 "recipient_name TEXT, "
                 "message_text TEXT, "
                 "status TEXT"
                 ")")
  cursor.execute("CREATE TABLE messages_for_owner ("
                 "id INTEGER PRIMARY KEY AUTOINCREMENT, "
                 "sender_name TEXT, "
                 "sender_id TEXT, "
                 "chat_name TEXT, "
                 "chat_id TEXT, "
                 "message_text TEXT, "
                 "timestamp DATETIME, "
                 "read_status TEXT"
                 ")")
  cursor.execute("CREATE TABLE event_proposals ("
                 "proposal_id TEXT, "
                 "summary TEXT, "
                 "start_iso TEXT, "
                 "end_iso TEXT, "
                 "description TEXT, "
                 "requester_id TEXT, "
                 "status TEXT"
                 ")")
  conn.commit()
  conn.close()
  return str(db_path)


# ── handle_find_whatsapp_chat ─────────────────────────────────────────


class TestHandleFindWhatsappChat:

  def test_no_matches(self, db_tools_db_path):
    result = db_tools.handle_find_whatsapp_chat({"name": "Nobody"}, db_tools_db_path)
    assert "No contacts found matching 'Nobody'" in result

  def test_exact_match(self, db_tools_db_path):
    _insert_contacts(db_tools_db_path, [
      ("c1", "Alice", "2025-07-01"),
    ])
    result = db_tools.handle_find_whatsapp_chat({"name": "Alice"}, db_tools_db_path)
    assert "Matches for 'Alice'" in result
    assert "- Alice (ID: c1)" in result

  def test_partial_match(self, db_tools_db_path):
    _insert_contacts(db_tools_db_path, [
      ("c1", "Alice Smith", "2025-07-01"),
      ("c2", "Bob Jones", "2025-07-01"),
    ])
    result = db_tools.handle_find_whatsapp_chat({"name": "Alice"}, db_tools_db_path)
    assert "Alice Smith" in result
    assert "Bob Jones" not in result

  def test_ordered_by_last_seen_desc(self, db_tools_db_path):
    _insert_contacts(db_tools_db_path, [
      ("c1", "Alice", "2025-06-01"),
      ("c2", "Alice", "2025-07-01"),
    ])
    result = db_tools.handle_find_whatsapp_chat({"name": "Alice"}, db_tools_db_path)
    lines = result.split("\n")
    # First match line should be the more recent one (c2)
    assert "c2" in lines[1]
    assert "c1" in lines[2]


# ── handle_propose_whatsapp_message ───────────────────────────────────


class TestHandleProposeWhatsappMessage:

  def test_inserts_and_returns_id(self, db_tools_db_path):
    result = db_tools.handle_propose_whatsapp_message(
      {
        "chat_id": "c1",
        "recipient_name": "Alice",
        "message_text": "Hello!",
      }, db_tools_db_path)
    assert result.startswith("[Proposal: ")
    assert result.endswith("]")

    # Verify DB row
    conn = sqlite3.connect(db_tools_db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT proposal_id, status FROM whatsapp_proposals")
    row = cursor.fetchone()
    conn.close()
    assert row[0] == result[len("[Proposal: "):-1]
    assert row[1] == "pending"

  def test_stores_all_fields(self, db_tools_db_path):
    db_tools.handle_propose_whatsapp_message({
      "chat_id": "c99",
      "recipient_name": "Bob",
      "message_text": "Hey there",
    }, db_tools_db_path)
    conn = sqlite3.connect(db_tools_db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT chat_id, recipient_name, message_text FROM whatsapp_proposals")
    row = cursor.fetchone()
    conn.close()
    assert row[0] == "c99"
    assert row[1] == "Bob"
    assert row[2] == "Hey there"


# ── handle_count_pending_messages ─────────────────────────────────────


class TestHandleCountPendingMessages:

  def test_zero_unread(self, db_tools_db_path):
    result = db_tools.handle_count_pending_messages(db_tools_db_path)
    assert "0 pending" in result

  def test_multiple_unread(self, db_tools_db_path):
    _insert_messages(db_tools_db_path, [
      ("Alice", "s1", "Family", "c1", "Hi", "2025-07-01 10:00", "unread"),
      ("Bob", "s2", "Work", "c2", "Hey", "2025-07-01 11:00", "unread"),
      ("Carol", "s3", "Family", "c1", "Read me", "2025-07-01 12:00", "read"),
    ])
    result = db_tools.handle_count_pending_messages(db_tools_db_path)
    assert "2 pending" in result


# ── handle_get_pending_messages ───────────────────────────────────────


class TestHandleGetPendingMessages:

  def test_no_pending(self, db_tools_db_path):
    result = db_tools.handle_get_pending_messages(db_tools_db_path)
    assert "No pending messages" in result

  def test_multiple_pending(self, db_tools_db_path):
    _insert_messages(db_tools_db_path, [
      ("Alice", "s1", "Family", "c1", "Hello", "2025-07-01 10:00", "unread"),
      ("Bob", "s2", "Work", "c2", "Meeting?", "2025-07-01 11:00", "unread"),
    ])
    result = db_tools.handle_get_pending_messages(db_tools_db_path)
    assert "2 message(s) waiting" in result
    assert "From: Alice" in result
    assert "From: Bob" in result
    assert "Context: Family" in result
    assert "Message: Hello" in result
    assert "Message: Meeting?" in result

  def test_ordered_by_timestamp_desc(self, db_tools_db_path):
    _insert_messages(db_tools_db_path, [
      ("Alice", "s1", "Family", "c1", "First", "2025-07-01 10:00", "unread"),
      ("Bob", "s2", "Work", "c2", "Second", "2025-07-01 12:00", "unread"),
    ])
    result = db_tools.handle_get_pending_messages(db_tools_db_path)
    # Bob (12:00) should appear before Alice (10:00)
    bob_pos = result.index("From: Bob")
    alice_pos = result.index("From: Alice")
    assert bob_pos < alice_pos


# ── fetch_whatsapp_proposal ───────────────────────────────────────────


class TestGetWhatsappProposal:

  def test_found(self, db_tools_db_path):
    db_tools.handle_propose_whatsapp_message({
      "chat_id": "c1",
      "recipient_name": "Alice",
      "message_text": "Hello!",
    }, db_tools_db_path)
    proposal_id = "abc123"
    conn = sqlite3.connect(db_tools_db_path)
    conn.execute("UPDATE whatsapp_proposals SET proposal_id = ?", (proposal_id,))
    conn.commit()
    conn.close()

    result = db_tools.get_whatsapp_proposal(proposal_id, db_tools_db_path)
    assert result == ("c1", "Alice", "Hello!", "pending")

  def test_not_found(self, db_tools_db_path):
    result = db_tools.get_whatsapp_proposal("nonexistent", db_tools_db_path)
    assert result is None


# ── get_contact_by_chat_id ────────────────────────────────────────────


class TestGetContactByChatId:

  def test_found(self, db_tools_db_path):
    _insert_contacts(db_tools_db_path, [
      ("c1", "Alice", "2025-07-01"),
    ])
    result = db_tools.get_contact_by_chat_id("c1", db_tools_db_path)
    assert result == "Alice"

  def test_not_found(self, db_tools_db_path):
    result = db_tools.get_contact_by_chat_id("missing", db_tools_db_path)
    assert result is None


# ── search_contacts_by_name ───────────────────────────────────────────


class TestSearchContactsByName:

  def test_no_matches(self, db_tools_db_path):
    result = db_tools.search_contacts_by_name("Nobody", db_tools_db_path)
    assert result == []

  def test_partial_match(self, db_tools_db_path):
    _insert_contacts(db_tools_db_path, [
      ("c1", "Alice Smith", "2025-07-01"),
      ("c2", "Bob Jones", "2025-07-01"),
    ])
    result = db_tools.search_contacts_by_name("Alice", db_tools_db_path)
    assert len(result) == 1
    assert result[0] == ("c1", "Alice Smith")

  def test_multiple_matches(self, db_tools_db_path):
    _insert_contacts(db_tools_db_path, [
      ("c1", "Alice Smith", "2025-07-01"),
      ("c2", "Alice Jones", "2025-07-01"),
    ])
    result = db_tools.search_contacts_by_name("Alice", db_tools_db_path)
    assert len(result) == 2


# ── find_contact_in_allowed ───────────────────────────────────────────


class TestFindContactInAllowed:

  def test_found(self, db_tools_db_path):
    _insert_contacts(db_tools_db_path, [
      ("c1@g.us", "Family Group", "2025-07-01"),
      ("c2@g.us", "Work Group", "2025-07-01"),
    ])
    result = db_tools.find_contact_in_allowed("Family", ["c1@g.us", "c2@g.us"], db_tools_db_path)
    assert result == "c1@g.us"

  def test_not_found(self, db_tools_db_path):
    _insert_contacts(db_tools_db_path, [
      ("c1@g.us", "Family Group", "2025-07-01"),
    ])
    result = db_tools.find_contact_in_allowed("Work", ["c1@g.us"], db_tools_db_path)
    assert result is None

  def test_empty_allowed(self, db_tools_db_path):
    result = db_tools.find_contact_in_allowed("Anything", [], db_tools_db_path)
    assert result is None


# ── list_contacts ─────────────────────────────────────────────────────


class TestListContacts:

  def test_all(self, db_tools_db_path):
    _insert_contacts(db_tools_db_path, [
      ("c1", "Alice", "2025-07-01"),
      ("c2@g.us", "Family Group", "2025-07-01"),
      ("status@broadcast", "Status", "2025-07-01"),
    ])
    result = db_tools.list_contacts(db_tools_db_path)
    names = [row[0] for row in result]
    assert "Alice" in names
    assert "Family Group" in names
    assert "Status" not in names

  def test_groups_only(self, db_tools_db_path):
    _insert_contacts(db_tools_db_path, [
      ("c1", "Alice", "2025-07-01"),
      ("c2@g.us", "Family Group", "2025-07-01"),
    ])
    result = db_tools.list_contacts(db_tools_db_path, 'groups')
    assert len(result) == 1
    assert result[0] == ("Family Group", "c2@g.us")

  def test_private_only(self, db_tools_db_path):
    _insert_contacts(db_tools_db_path, [
      ("c1", "Alice", "2025-07-01"),
      ("c2@g.us", "Family Group", "2025-07-01"),
    ])
    result = db_tools.list_contacts(db_tools_db_path, 'private')
    assert len(result) == 1
    assert result[0] == ("Alice", "c1")

  def test_empty(self, db_tools_db_path):
    result = db_tools.list_contacts(db_tools_db_path)
    assert result == []


# ── get_event_proposal ────────────────────────────────────────────────


class TestGetEventProposal:

  def test_found(self, db_tools_db_path):
    conn = sqlite3.connect(db_tools_db_path)
    conn.execute(
      "INSERT INTO event_proposals (proposal_id, summary, start_iso, end_iso, description, requester_id, status) "
      "VALUES (?, ?, ?, ?, ?, ?, ?)",
      ("ep1", "Team Meeting", "2025-08-01T10:00", "2025-08-01T11:00", "Discuss Q3", "u1", "pending"),
    )
    conn.commit()
    conn.close()
    result = db_tools.get_event_proposal("ep1", db_tools_db_path)
    assert result == ("Team Meeting", "2025-08-01T10:00", "2025-08-01T11:00", "Discuss Q3", "u1")

  def test_not_found(self, db_tools_db_path):
    result = db_tools.get_event_proposal("missing", db_tools_db_path)
    assert result is None


# ── update_event_proposal_status ──────────────────────────────────────


class TestUpdateEventProposalStatus:

  def test_update(self, db_tools_db_path):
    conn = sqlite3.connect(db_tools_db_path)
    conn.execute(
      "INSERT INTO event_proposals (proposal_id, summary, start_iso, end_iso, description, requester_id, status) "
      "VALUES (?, ?, ?, ?, ?, ?, ?)",
      ("ep1", "Team Meeting", "2025-08-01T10:00", "2025-08-01T11:00", "Discuss Q3", "u1", "pending"),
    )
    conn.commit()
    conn.close()
    db_tools.update_event_proposal_status("ep1", "approved", db_tools_db_path)
    conn = sqlite3.connect(db_tools_db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT status FROM event_proposals WHERE proposal_id = ?", ("ep1",))
    assert cursor.fetchone()[0] == "approved"
    conn.close()


# ── update_whatsapp_proposal_status ───────────────────────────────────


class TestUpdateWhatsappProposalStatus:

  def test_update(self, db_tools_db_path):
    db_tools.handle_propose_whatsapp_message({
      "chat_id": "c1",
      "recipient_name": "Alice",
      "message_text": "Hello!",
    }, db_tools_db_path)
    conn = sqlite3.connect(db_tools_db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT proposal_id FROM whatsapp_proposals")
    proposal_id = cursor.fetchone()[0]
    conn.close()
    db_tools.update_whatsapp_proposal_status(proposal_id, "sent", db_tools_db_path)
    conn = sqlite3.connect(db_tools_db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT status FROM whatsapp_proposals WHERE proposal_id = ?", (proposal_id,))
    assert cursor.fetchone()[0] == "sent"
    conn.close()


# ── handle_clear_messages ─────────────────────────────────────────────


class TestHandleClearMessages:

  def test_clear_all(self, db_tools_db_path):
    _insert_messages(db_tools_db_path, [
      ("Alice", "s1", "Family", "c1", "Hi", "2025-07-01 10:00", "unread"),
      ("Bob", "s2", "Work", "c2", "Hey", "2025-07-01 11:00", "unread"),
      ("Carol", "s3", "Family", "c1", "Read", "2025-07-01 12:00", "read"),
    ])
    result = db_tools.handle_clear_messages({"mode": "all"}, db_tools_db_path)
    assert "Cleared 2 message(s)" in result

    # Verify all are now read
    conn = sqlite3.connect(db_tools_db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM messages_for_owner WHERE read_status = 'unread'")
    count = cursor.fetchone()[0]
    conn.close()
    assert count == 0

  def test_clear_by_ids(self, db_tools_db_path):
    _insert_messages(db_tools_db_path, [
      ("Alice", "s1", "Family", "c1", "Hi", "2025-07-01 10:00", "unread"),
      ("Bob", "s2", "Work", "c2", "Hey", "2025-07-01 11:00", "unread"),
      ("Carol", "s3", "Family", "c1", "Read", "2025-07-01 12:00", "unread"),
    ])
    result = db_tools.handle_clear_messages({"mode": "ids", "ids": [1, 3]}, db_tools_db_path)
    assert "Cleared 2 message(s)" in result

    # Only Bob (id=2) should still be unread
    conn = sqlite3.connect(db_tools_db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM messages_for_owner WHERE read_status = 'unread'")
    count = cursor.fetchone()[0]
    conn.close()
    assert count == 1

  def test_clear_by_ids_no_match(self, db_tools_db_path):
    _insert_messages(db_tools_db_path, [
      ("Alice", "s1", "Family", "c1", "Hi", "2025-07-01 10:00", "unread"),
    ])
    result = db_tools.handle_clear_messages({"mode": "ids", "ids": [999]}, db_tools_db_path)
    assert "Cleared 0 message(s)" in result

  def test_clear_empty_ids(self, db_tools_db_path):
    _insert_messages(db_tools_db_path, [
      ("Alice", "s1", "Family", "c1", "Hi", "2025-07-01 10:00", "unread"),
    ])
    result = db_tools.handle_clear_messages({"mode": "ids", "ids": []}, db_tools_db_path)
    assert "Cleared 0 message(s)" in result
