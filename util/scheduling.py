"""Scheduling tool handlers and helpers.

Pure helpers (validate_schedule_args, normalize_execution_time, flatten_schedule_params)
are testable in isolation with no side effects.
"""

import json
import os
import sqlite3
import uuid
import datetime
import pytz
import requests
import html as html_mod

from absl import logging

SCHEDULE_ACTION_MAP = {
  'schedule_telegram_reminder': 'send_telegram_reminder',
  'schedule_whatsapp_message': 'send_whatsapp_message',
  'schedule_whatsapp_summary': 'send_summary',
  'schedule_llm_task': 'llm_task',
}


def validate_schedule_args(args):
  """Validate scheduling arguments.

    Returns (execution_time, cron, error_msg).
    error_msg is non-None on validation failure.
    """
  execution_time = args.get('execution_time')
  if not execution_time:
    return None, None, "Error: execution_time is required. Cannot schedule a task with no time specified."

  cron = args.get('cron_expression')
  is_recurring = args.get('is_recurring', False)
  if is_recurring and not cron:
    return None, None, "Error: cron_expression is required for recurring tasks."

  return execution_time, cron, None


def normalize_execution_time(execution_time):
  """Parse ISO time string, localize to SG if naive, convert to UTC.

    Returns (utc_iso_string, error_msg). error_msg is non-None on parse failure.
    """
  try:
    original_time = execution_time
    dt = datetime.datetime.fromisoformat(execution_time)
    if dt.tzinfo is None:
      dt = pytz.timezone('Asia/Singapore').localize(dt)
    utc_time = dt.astimezone(pytz.utc).isoformat()
    logging.info(f"Schedule: LLM sent '{original_time}', stored as UTC '{utc_time}'")
    return utc_time, None
  except (ValueError, TypeError) as e:
    logging.error(f"Error parsing execution_time {execution_time}: {e}")
    return None, (f"Error: could not parse execution_time '{execution_time}'. "
                  "Please provide a valid ISO timestamp (e.g., 2025-06-15T09:00:00).")


def flatten_schedule_params(args):
  """Strip execution_time and cron_expression from args, return remaining as params."""
  return {k: v for k, v in args.items() if k not in ('execution_time', 'cron_expression')}


def insert_scheduled_task(db_path, task_id, owner_id, execution_time, action, params, cron):
  """Insert a scheduled task row into the DB."""
  conn = sqlite3.connect(db_path)
  cursor = conn.cursor()
  cursor.execute(
    "INSERT INTO scheduled_tasks (task_id, owner_id, execution_time, action_type, action_params, cron_expression, status) VALUES (?, ?, ?, ?, ?, ?, ?)",
    (task_id, owner_id, execution_time, action, json.dumps(params), cron, 'pending'),
  )
  conn.commit()
  conn.close()


def load_scheduling_credentials(cfg):
  """Load bot token, owner ID, and owner timezone from config/files.

    Args:
      cfg: dict loaded from config.load_config().

    Returns:
      dict with keys 'bot_token', 'owner_id', 'owner_tz'.

    Raises:
      RuntimeError: if credentials cannot be loaded or are misconfigured.
    """
  try:
    from core_brain import ROOT_DIR
    with open(os.path.join(ROOT_DIR, 'token'), 'r') as f:
      bot_token = f.read().strip()
    owner = cfg.get('owner', {})
    owner_id = owner.get('owner_chat_id', owner.get('chat_id', ''))
    owner_tz = pytz.timezone(owner.get('timezone', 'UTC'))
  except (ImportError, FileNotFoundError) as e:
    logging.error(f"load_scheduling_credentials: failed to load credentials: {e}")
    raise RuntimeError(f"Cannot load scheduling credentials: {e}") from e
  except pytz.exceptions.UnknownTimeZoneError as e:
    logging.error(f"load_scheduling_credentials: unknown timezone: {e}")
    raise RuntimeError(f"Invalid timezone in config: {e}") from e

  if not owner_id:
    logging.error("load_scheduling_credentials: no owner_id configured")
    raise RuntimeError("No owner_chat_id configured")

  return {'bot_token': bot_token, 'owner_id': owner_id, 'owner_tz': owner_tz}


def format_execution_time_for_display(execution_time, owner_tz):
  """Convert a UTC ISO timestamp to a human-readable string in the owner's timezone.

    Args:
      execution_time: ISO format datetime string.
      owner_tz: a pytz timezone object.

    Returns:
      Formatted string like '2025-06-15 09:00 SGT', or the original string on failure.

    Raises:
      RuntimeError: if the time cannot be parsed or converted.
    """
  time_display = execution_time
  if execution_time:
    try:
      dt = datetime.datetime.fromisoformat(execution_time)
      time_display = dt.astimezone(owner_tz).strftime('%Y-%m-%d %H:%M %Z')
    except (ValueError, pytz.exceptions.UnknownTimeZoneError) as e:
      logging.error(f"format_execution_time_for_display: failed to convert time for display: {e}")
      raise RuntimeError(f"Cannot format execution time: {e}") from e
  return time_display


def build_detail_lines(action, params):
  """Build action-specific detail lines for a scheduling confirmation message.

    Args:
      action: the action type string.
      params: dict of action parameters.

    Returns:
      List of formatted strings (may be empty).
    """
  detail_lines = []
  if action == 'send_whatsapp_message':
    recipients = params.get('recipients', []) or [params.get('chat_id', 'Unknown')]
    detail_lines.append(f"To: {', '.join(recipients)}")
    detail_lines.append(f"Message: {params.get('message_text', '(empty)')}")
  elif action == 'send_telegram_reminder':
    detail_lines.append(f"Reminder: {params.get('message_text', '(empty)')}")
  elif action == 'send_summary':
    detail_lines.append(f"Group: {params.get('group', 'Unknown')}")
  elif action == 'llm_task':
    detail_lines.append(f"Task: {params.get('prompt', '(empty)')}")
  return detail_lines


def build_confirmation_message(task_id, action, params, time_display, cron):
  """Assemble the full HTML confirmation message text.

    Args:
      task_id: the scheduled task ID.
      action: the action type string.
      params: dict of action parameters.
      time_display: pre-formatted human-readable time string.
      cron: cron expression string or None.

    Returns:
      The complete HTML-formatted message string.
    """
  detail_lines = build_detail_lines(action, params)
  cron_display = f"\nRecurrence: {cron}" if cron else ""
  return (f"<b>📅 Task Scheduled</b>\n\n"
          f"ID: {task_id}\n"
          f"Action: {action}\n"
          f"Time: {time_display}{cron_display}\n\n" + "\n".join(f"{html_mod.escape(line)}" for line in detail_lines))


def send_telegram_message(bot_token, chat_id, text):
  """Send a message via the Telegram Bot API.

    Args:
      bot_token: Telegram bot token.
      chat_id: target chat ID.
      text: message text (HTML format).

    Raises:
      RuntimeError: if the API request fails.
    """
  try:
    response = requests.post(
      f"https://api.telegram.org/bot{bot_token}/sendMessage",
      json={
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
      },
    )
    response.raise_for_status()
  except requests.exceptions.RequestException as e:
    logging.error(f"send_telegram_message: Telegram API error: {e}")
    raise RuntimeError(f"Failed to send confirmation notification: {e}") from e


def send_scheduling_confirmation(task_id, action, params, execution_time, cron):
  """Send a Telegram notification confirming the scheduled task details."""
  import util.config as config

  cfg = config.load_config()
  creds = load_scheduling_credentials(cfg)
  time_display = format_execution_time_for_display(execution_time, creds['owner_tz'])
  text = build_confirmation_message(task_id, action, params, time_display, cron)
  send_telegram_message(creds['bot_token'], creds['owner_id'], text)


def handle_schedule_task(tool_name, args, session_id, db_path):
  """Handle the 4 schedule_* tools.

    Returns a result string on success/error, or None if tool_name is not a scheduling tool.
    """
  if tool_name not in SCHEDULE_ACTION_MAP:
    return None

  action = SCHEDULE_ACTION_MAP[tool_name]
  execution_time, cron, error_msg = validate_schedule_args(args)
  if error_msg:
    return error_msg

  utc_time, parse_error = normalize_execution_time(execution_time)
  if parse_error:
    return parse_error

  params = flatten_schedule_params(args)
  task_id = str(uuid.uuid4())[:8]

  try:
    insert_scheduled_task(db_path, task_id, session_id, utc_time, action, params, cron)
  except (sqlite3.Error, RuntimeError) as e:
    logging.error(f"handle_schedule_task: failed to insert task {task_id}: {e}")
    return f"Error: failed to schedule task: {e}"

  try:
    send_scheduling_confirmation(task_id, action, params, utc_time, cron)
  except RuntimeError as e:
    return f"Task scheduled (ID: {task_id}) but failed to send confirmation: {e}"

  return f"Task scheduled successfully (ID: {task_id})."


def handle_list_scheduled_tasks(db_path):
  """Handle list_scheduled_tasks.

    Returns a formatted string of pending tasks.
    """
  conn = sqlite3.connect(db_path)
  cursor = conn.cursor()
  cursor.execute(
    "SELECT task_id, execution_time, action_type, action_params FROM scheduled_tasks WHERE status = 'pending'")
  tasks = cursor.fetchall()
  conn.close()
  if not tasks:
    return "No pending scheduled tasks found."

  output = ["Upcoming Scheduled Tasks:"]
  for t in tasks:
    output.append(f"- {t[0]}: {t[1]} | Action: {t[2]} | Params: {t[3]}")
  return "\n".join(output)


def handle_cancel_scheduled_task(args, db_path):
  """Handle cancel_scheduled_task.

    Returns a confirmation string.
    """
  task_id = args.get('task_id')
  conn = sqlite3.connect(db_path)
  cursor = conn.cursor()
  cursor.execute("UPDATE scheduled_tasks SET status = 'cancelled' WHERE task_id = ?", (task_id,))
  conn.commit()
  conn.close()
  return f"Task {task_id} has been cancelled."
