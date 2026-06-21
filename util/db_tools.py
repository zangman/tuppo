"""WhatsApp database tool handlers.

Each function accepts db_path so tests can pass in-memory SQLite paths.
"""

import sqlite3
import uuid


def handle_find_whatsapp_chat(args, db_path):
  """Search contacts by name.

    Returns formatted matches string, or None if tool_name doesn't match.
    """
  name = args.get('name', '')
  conn = sqlite3.connect(db_path, timeout=10.0)
  cursor = conn.cursor()
  cursor.execute(
    "SELECT chat_id, display_name FROM contacts WHERE display_name LIKE ? ORDER BY last_seen DESC",
    (f"%{name}%",),
  )
  matches = cursor.fetchall()
  conn.close()
  if not matches:
    return f"No contacts found matching '{name}'."
  output = [f"Matches for '{name}':"]
  for chat_id, display_name in matches:
    output.append(f"- {display_name} (ID: {chat_id})")
  return "\n".join(output)


def handle_propose_whatsapp_message(args, db_path):
  """Insert a message proposal.

    Returns [Proposal: <id>] string.
    """
  proposal_id = str(uuid.uuid4())[:8]
  chat_id = args.get('chat_id')
  recipient_name = args.get('recipient_name')
  message_text = args.get('message_text')
  conn = sqlite3.connect(db_path, timeout=10.0)
  cursor = conn.cursor()
  cursor.execute(
    "INSERT INTO whatsapp_proposals (proposal_id, chat_id, recipient_name, message_text, status) VALUES (?, ?, ?, ?, ?)",
    (proposal_id, chat_id, recipient_name, message_text, 'pending'),
  )
  conn.commit()
  conn.close()
  return f"[Proposal: {proposal_id}]"


def handle_count_pending_messages(db_path):
  """Count unread messages.

    Returns count string.
    """
  conn = sqlite3.connect(db_path, timeout=10.0)
  cursor = conn.cursor()
  cursor.execute("SELECT COUNT(*) FROM messages_for_owner WHERE read_status = 'unread'")
  count = cursor.fetchone()[0]
  conn.close()
  return f"You have {count} pending message(s)."


def handle_get_pending_messages(db_path):
  """Retrieve unread messages.

    Returns formatted list of messages.
    """
  conn = sqlite3.connect(db_path, timeout=10.0)
  cursor = conn.cursor()
  cursor.execute("SELECT id, sender_name, sender_id, chat_name, chat_id, message_text, timestamp, read_status "
                 "FROM messages_for_owner WHERE read_status = 'unread' ORDER BY timestamp DESC")
  messages = cursor.fetchall()
  conn.close()
  if not messages:
    return "No pending messages for you."
  output = [f"You have {len(messages)} message(s) waiting:"]
  for msg_id, sender_name, _sender_id, chat_name, _chat_id, message_text, timestamp, _read_status in messages:
    output.append(f"\nMessage #{msg_id}:")
    output.append(f"  From: {sender_name}")
    output.append(f"  Context: {chat_name}")
    output.append(f"  Time: {timestamp}")
    output.append(f"  Message: {message_text}")
  return "\n".join(output)


def get_whatsapp_proposal(proposal_id, db_path):
  """Fetch a WhatsApp message proposal by ID.

  Returns (chat_id, recipient_name, message_text, status) or None if not found.
  """
  conn = sqlite3.connect(db_path, timeout=10.0)
  cursor = conn.cursor()
  cursor.execute(
    "SELECT chat_id, recipient_name, message_text, status FROM whatsapp_proposals WHERE proposal_id = ?",
    (proposal_id,),
  )
  row = cursor.fetchone()
  conn.close()
  return row


def get_contact_by_chat_id(chat_id, db_path):
  """Return display_name for a given chat_id, or None if not found."""
  conn = sqlite3.connect(db_path, timeout=10.0)
  cursor = conn.cursor()
  cursor.execute("SELECT display_name FROM contacts WHERE chat_id = ?", (chat_id,))
  row = cursor.fetchone()
  conn.close()
  return row[0] if row else None


def search_contacts_by_name(name_query, db_path):
  """Return list of (chat_id, display_name) matching display_name LIKE %query%."""
  conn = sqlite3.connect(db_path, timeout=10.0)
  cursor = conn.cursor()
  cursor.execute(
    "SELECT chat_id, display_name FROM contacts WHERE display_name LIKE ?",
    (f"%{name_query}%",),
  )
  matches = cursor.fetchall()
  conn.close()
  return matches


def find_contact_in_allowed(name_query, allowed_ids, db_path):
  """Return chat_id if a contact matching name_query is in allowed_ids, else None."""
  if not allowed_ids:
    return None
  conn = sqlite3.connect(db_path, timeout=10.0)
  cursor = conn.cursor()
  placeholders = ','.join('?' * len(allowed_ids))
  cursor.execute(
    f"SELECT chat_id FROM contacts WHERE display_name LIKE ? AND chat_id IN ({placeholders})",
    (f"%{name_query}%",) + tuple(allowed_ids),
  )
  row = cursor.fetchone()
  conn.close()
  return row[0] if row else None


def list_contacts(db_path, filter_type='all'):
  """Return list of (display_name, chat_id) ordered by display_name.

  filter_type: 'groups', 'private', or 'all' (default).
  """
  conn = sqlite3.connect(db_path, timeout=10.0)
  cursor = conn.cursor()
  if filter_type == 'groups' or filter_type == 'group':
    cursor.execute("SELECT display_name, chat_id FROM contacts WHERE chat_id LIKE '%@g.us' ORDER BY display_name")
  elif filter_type == 'private' or filter_type == 'people':
    cursor.execute(
      "SELECT display_name, chat_id FROM contacts WHERE chat_id NOT LIKE '%@g.us' AND chat_id != 'status@broadcast' ORDER BY display_name"
    )
  else:
    cursor.execute(
      "SELECT display_name, chat_id FROM contacts WHERE chat_id != 'status@broadcast' ORDER BY display_name")
  rows = cursor.fetchall()
  conn.close()
  return rows


def get_event_proposal(proposal_id, db_path):
  """Return (summary, start_iso, end_iso, description, requester_id) or None."""
  conn = sqlite3.connect(db_path, timeout=10.0)
  cursor = conn.cursor()
  cursor.execute(
    "SELECT summary, start_iso, end_iso, description, requester_id FROM event_proposals WHERE proposal_id = ?",
    (proposal_id,),
  )
  row = cursor.fetchone()
  conn.close()
  return row


def update_event_proposal_status(proposal_id, status, db_path):
  """Update status of an event proposal."""
  conn = sqlite3.connect(db_path, timeout=10.0)
  cursor = conn.cursor()
  cursor.execute(
    "UPDATE event_proposals SET status = ? WHERE proposal_id = ?",
    (status, proposal_id),
  )
  conn.commit()
  conn.close()


def update_whatsapp_proposal_status(proposal_id, status, db_path):
  """Update status of a WhatsApp message proposal."""
  conn = sqlite3.connect(db_path, timeout=10.0)
  cursor = conn.cursor()
  cursor.execute(
    "UPDATE whatsapp_proposals SET status = ? WHERE proposal_id = ?",
    (status, proposal_id),
  )
  conn.commit()
  conn.close()


def handle_clear_messages(args, db_path):
  """Mark messages as read.

    Returns confirmation string.
    """
  mode = args.get('mode', 'all')
  conn = sqlite3.connect(db_path, timeout=10.0)
  cursor = conn.cursor()
  if mode == 'all':
    cursor.execute("UPDATE messages_for_owner SET read_status = 'read' WHERE read_status = 'unread'")
    cleared = cursor.rowcount
  else:
    ids = args.get('ids', [])
    if ids:
      placeholders = ','.join('?' * len(ids))
      cursor.execute(f"UPDATE messages_for_owner SET read_status = 'read' WHERE id IN ({placeholders})", ids)
      cleared = cursor.rowcount
    else:
      cleared = 0
  conn.commit()
  conn.close()
  return f"Cleared {cleared} message(s)."
