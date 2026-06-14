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
  for msg_id, sender_name, sender_id, chat_name, chat_id, message_text, timestamp, read_status in messages:
    output.append(f"\nMessage #{msg_id}:")
    output.append(f"  From: {sender_name}")
    output.append(f"  Context: {chat_name}")
    output.append(f"  Time: {timestamp}")
    output.append(f"  Message: {message_text}")
  return "\n".join(output)


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
