import sqlite3
import os
import logging
import pytz
import datetime

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(ROOT_DIR, "whatsapp.db")
_MAX_OUTPUT_CHARS = 3500


def _get_owner_timezone():
  """Get owner timezone from config.yaml."""
  import util.config as config
  return config.load_config().get('owner', {}).get('timezone', 'UTC')


def _utc_to_local(utc_str: str) -> str:
  """Convert a UTC timestamp string to the owner's local timezone."""
  try:
    utc_tz = pytz.timezone('UTC')
    local_tz = pytz.timezone(_get_owner_timezone())
    dt = utc_tz.localize(datetime.datetime.strptime(utc_str, "%Y-%m-%d %H:%M:%S"))
    return dt.astimezone(local_tz).strftime("%Y-%m-%d %H:%M:%S %Z")
  except Exception:
    return utc_str  # fallback to raw string if conversion fails


def _format_time_local(timestamp_str: str) -> str:
  """Extract just the time portion (HH:MM) in local timezone."""
  try:
    utc_tz = pytz.timezone('UTC')
    local_tz = pytz.timezone(_get_owner_timezone())
    dt = utc_tz.localize(datetime.datetime.strptime(timestamp_str, "%Y-%m-%d %H:%M:%S"))
    return dt.astimezone(local_tz).strftime("%H:%M")
  except Exception:
    # fallback: extract time from raw string
    return timestamp_str.split(" ")[1][:5] if " " in timestamp_str else timestamp_str


def get_new_messages(chat_name_query: str = None) -> str:
  """
    Retrieve only NEW WhatsApp messages since the last check for a given chat.
    Uses a per-chat bookmark (last_read_timestamp) to track what has been read.
    Advances the bookmark after each fetch so messages are never returned twice.
    If chat_name_query is not given, lists active chats.
    """
  if not os.path.exists(DB_PATH):
    return "Error: WhatsApp database does not exist yet. Please make sure the WhatsApp logging server is running."

  try:
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Case 1: No chat name query specified -> List active chats
    if not chat_name_query:
      logging.info(f'got chat name {chat_name_query}')
      result = _list_active_chats(cursor)
      conn.close()
      return result

    # Case 2: Query specified -> Find matching chat
    group_id, group_name = _resolve_chat(cursor, chat_name_query)
    if not group_id:
      return _not_found_response(chat_name_query, cursor)

    # 1. Get the last read timestamp (bookmark)
    cursor.execute("SELECT last_read_timestamp FROM chat_status WHERE chat_id = ?", (group_id,))
    row = cursor.fetchone()

    if row:
      last_read = row[0]
    else:
      # First time reading this chat: start from the 1000th most recent message
      cursor.execute(
        "SELECT timestamp FROM whatsapp_messages WHERE group_id = ? ORDER BY timestamp DESC LIMIT 1 OFFSET 999",
        (group_id,))
      row_start = cursor.fetchone()
      if row_start:
        last_read = row_start[0]
      else:
        # Fewer than 1000 messages exist; start from the absolute oldest
        cursor.execute("SELECT MIN(timestamp) FROM whatsapp_messages WHERE group_id = ?", (group_id,))
        row_min = cursor.fetchone()
        last_read = row_min[0] if row_min and row_min[0] else "1970-01-01 00:00:00"

    # 2. Fetch messages since that timestamp
    cursor.execute(
      """SELECT sender, text, timestamp
               FROM whatsapp_messages
               WHERE group_id = ? AND timestamp > ?
               ORDER BY timestamp ASC""", (group_id, last_read))
    messages = cursor.fetchall()

    if not messages:
      conn.close()
      local_last_read = _utc_to_local(last_read)
      return f"Chat found: '{group_name}', but there are no new unread messages since {local_last_read} (local time)."

    # 3. Update the bookmark to the timestamp of the most recent message fetched
    latest_timestamp = messages[-1][2]
    cursor.execute(
      "INSERT INTO chat_status (chat_id, last_read_timestamp) VALUES (?, ?) "
      "ON CONFLICT(chat_id) DO UPDATE SET last_read_timestamp = excluded.last_read_timestamp",
      (group_id, latest_timestamp))
    conn.commit()

    # Format transcript for LLM (clean and dense)
    transcript_lines = []
    for msg in messages:
      sender, text, timestamp = msg
      time_str = _format_time_local(timestamp)
      transcript_lines.append(f"[{time_str}] {sender}: {text}")

    full_output = "\n".join(transcript_lines)

    # Truncate if output is too long
    if len(full_output) > _MAX_OUTPUT_CHARS:
      truncated_lines = []
      current_len = 0
      messages_shown = 0
      total_count = len(transcript_lines)
      for line in transcript_lines:
        if current_len + len(line) + 1 > _MAX_OUTPUT_CHARS:
          break
        truncated_lines.append(line)
        current_len += len(line) + 1
        messages_shown += 1
      conn.close()
      return f"SUMMARY DATA (Truncated {messages_shown}/{total_count}):\n" + "\n".join(truncated_lines)

    conn.close()
    return "SUMMARY DATA:\n" + full_output

  except Exception as e:
    logging.error(f"Error querying WhatsApp DB: {e}")
    return f"Database query error: {e}"


def get_chat_history(chat_name_query: str, timeframe_hours: int = 24, search_text: str = None) -> str:
  """
    Fetch WhatsApp messages for a specific time range, optionally filtered by keyword.
    Does NOT use or advance the bookmark — always reads from the full history.
    Use this for historical lookups, topic searches, or arbitrary time ranges.
    """
  if not os.path.exists(DB_PATH):
    return "Error: WhatsApp database does not exist yet. Please make sure the WhatsApp logging server is running."

  try:
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Resolve chat
    group_id, group_name = _resolve_chat(cursor, chat_name_query)
    if not group_id:
      return _not_found_response(chat_name_query, cursor)

    # Build query with optional time range and text filter
    # Note: datetime() is an SQLite function, must be embedded in SQL, not passed as ?
    query = f"""SELECT sender, text, timestamp
                   FROM whatsapp_messages
                   WHERE group_id = ? AND timestamp >= datetime('now', '-{timeframe_hours} hours')"""
    params = [group_id]

    if search_text:
      query += " AND text LIKE ?"
      params.append(f"%{search_text}%")

    query += " ORDER BY timestamp ASC"

    cursor.execute(query, params)
    messages = cursor.fetchall()

    if not messages:
      conn.close()
      search_info = f" matching '{search_text}'" if search_text else ""
      return (f"Chat found: '{group_name}', but no messages{search_info} "
              f"in the last {timeframe_hours} hours.")

    # Format transcript
    header_parts = [f"=== Messages for '{group_name}' (last {timeframe_hours}h)"]
    if search_text:
      header_parts[0] += f", filtered by '{search_text}'"
    header_parts[0] += f" ==="

    transcript_lines = header_parts
    total_count = len(messages)

    # Build full output, then truncate if needed
    for msg in messages:
      sender, text, timestamp = msg
      time_str = _format_time_local(timestamp)
      transcript_lines.append(f"[{time_str}] {sender}: {text}")

    full_output = "\n".join(transcript_lines)

    # Truncate if output is too long for Telegram
    if len(full_output) > _MAX_OUTPUT_CHARS:
      # Rebuild with a message count note
      truncated_lines = [header_parts[0]]
      current_len = len(truncated_lines[0])
      messages_shown = 0
      for msg in messages:
        sender, text, timestamp = msg
        time_str = _format_time_local(timestamp)
        line = f"[{time_str}] {sender}: {text}"
        if current_len + len(line) + 1 > _MAX_OUTPUT_CHARS:
          break
        truncated_lines.append(line)
        current_len += len(line) + 1
        messages_shown += 1
      truncated_lines.append(f"\n[Truncated: showing {messages_shown} of {total_count} messages]")
      conn.close()
      return "\n".join(truncated_lines)

    conn.close()
    return full_output

  except Exception as e:
    logging.error(f"Error querying WhatsApp DB: {e}")
    return f"Database query error: {e}"


def _resolve_chat(cursor, chat_name_query: str):
  """Find a matching chat by name. Returns (group_id, group_name) or (None, None)."""
  cursor.execute("SELECT DISTINCT group_id, group_name FROM whatsapp_messages WHERE group_name LIKE ?",
                 (f"%{chat_name_query}%",))
  matches = cursor.fetchall()

  if not matches:
    return None, None

  if len(matches) > 1:
    # Return the first match (most recent by implicit DB order)
    # The caller can handle ambiguity if needed
    return matches[0]

  return matches[0]


def _not_found_response(chat_name_query, cursor):
  """Return a helpful response when no chat matches the query."""
  return f"No chats found matching '{chat_name_query}'.\n\n" + _list_active_chats(cursor)


def _list_active_chats(cursor) -> str:
  cursor.execute("""SELECT group_name, group_id, COUNT(*) as msg_count, MAX(timestamp) as last_msg
           FROM whatsapp_messages
           WHERE timestamp >= datetime('now', '-7 days')
           GROUP BY group_id
           ORDER BY last_msg DESC""")
  chats = cursor.fetchall()

  if not chats:
    return "No active WhatsApp chats found in the database from the last 7 days."

  lines = ["Active WhatsApp chats in the last 7 days:"]
  for chat in chats:
    name, chat_id, count, last_msg = chat
    local_last_msg = _utc_to_local(last_msg)
    lines.append(f"- {name} ({count} messages, last message: {local_last_msg} (local time))")

  return "\n".join(lines)

