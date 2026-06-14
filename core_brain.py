import asyncio
import copy
import json
import os
import requests
from absl import logging
import uuid
import sqlite3
import datetime
import pytz

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))

import util.get_time as get_time
import util.config as config
import tools.calc as calc
import tools.web_search as web_search
import tools.searxng_search as searxng_search
import tools.whatsapp_summary as whatsapp_summary
import tools.google_calendar as google_calendar
import tools.gmail as gmail
import tools.fetch_page as fetch_page
import tools.owner_profile as owner_profile
from tools.tool_definitions import PUBLIC_TOOLS, WHATSAPP_TOOLS, ADMIN_TOOLS

_CFG = config.load_config()
_BASE_URL = _CFG.get('llm', {}).get('base_url', 'http://localhost:8080')
_URL = f"{_BASE_URL}/v1/chat/completions"
_MODELS_URL = f"{_BASE_URL}/v1/models"

_HEADERS = {
  "User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:150.0) Gecko/20100101 Firefox/150.0",
  "Accept": "*/*",
  "Accept-Language": "en-US,en;q=0.9",
  "Accept-Encoding": "gzip, deflate, br, zstd",
  "Referer": f"{_BASE_URL}/",
  "Content-Type": "application/json",
  "Origin": _BASE_URL,
  "Connection": "keep-alive",
}

_STARTER_MESSAGES = [{
  "role":
    "system",
  "content": (
    "You are a highly efficient personal coordinator for the owner. You have access to various tools to manage their life and communications.\n\n"
    "IMPORTANT GUIDELINES FOR SUMMARIES:\n"
    "When you use tools to retrieve WhatsApp messages or chat history, your default goal is to synthesize the information into a concise, high-value summary rather than providing a transcript.\n"
    "1. **Summarize by Default**: Extract key takeaways, action items, and decisions using a short bulleted list.\n"
    "2. **Exact Quotes on Request**: If the user explicitly asks for a 'quote', 'exact message', 'specific text', or the 'full transcript', ignore the summary guideline and provide the precise text from the tool output.\n"
    "3. **Conciseness**: Unless providing a specific quote, avoid long blocks of text."
    "TOOL USAGE:\n"
    "When you call propose_whatsapp_message, output ONLY the returned [Proposal: <id>] tag with absolutely no additional text. "
    "The system will convert it into inline buttons for the user to approve or cancel. Any extra text you add will prevent the buttons from appearing."
  )
}]

# Session-based memory: { session_id: [messages] }
sessions = {}


def format_msg(tool_call_id, content):
  return {
    'role': 'tool',
    'tool_call_id': tool_call_id,
    'content': str(content),
  }


def _log_result(tool_name, content):
  """Log the result of a tool call, truncating long output."""
  text = str(content)[:500]
  if len(str(content)) > 500:
    text += '...'
  logging.info(f"TOOL RESULT: {tool_name} -> {text}")


def _tool_return(tool_name, tool_call_id, content):
  """Log the tool result and return the formatted message."""
  _log_result(tool_name, content)
  return format_msg(tool_call_id, content)


def _send_scheduling_confirmation(task_id, action, params, execution_time, cron):
  """Send a Telegram notification confirming the scheduled task details."""
  import html as html_mod

  try:
    with open(os.path.join(ROOT_DIR, 'token'), 'r') as f:
      bot_token = f.read().strip()
    owner = _CFG.get('owner', {})
    owner_id = owner.get('owner_chat_id', owner.get('chat_id', ''))
    owner_tz = pytz.timezone(owner.get('timezone', 'UTC'))
  except Exception:
    return

  if not owner_id:
    return

  # Convert execution_time to local timezone for readability
  time_display = execution_time
  if execution_time:
    try:
      dt = datetime.datetime.fromisoformat(execution_time)
      time_display = dt.astimezone(owner_tz).strftime('%Y-%m-%d %H:%M %Z')
    except Exception:
      pass

  # Build detail lines based on action type
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

  cron_display = f"\nRecurrence: {cron}" if cron else ""
  text = (f"<b>📅 Task Scheduled</b>\n\n"
          f"ID: {task_id}\n"
          f"Action: {action}\n"
          f"Time: {time_display}{cron_display}\n\n" + "\n".join(f"{html_mod.escape(l)}" for l in detail_lines))

  requests.post(
    f"https://api.telegram.org/bot{bot_token}/sendMessage",
    json={
      "chat_id": owner_id,
      "text": text,
      "parse_mode": "HTML"
    })


async def execute_tool(tc, session_id):
  tool_call_id = tc['id']
  tool_name = tc['function']['name']
  args = json.loads(tc['function']['arguments'])
  logging.info(f"TOOL CALL: {tool_name} args={json.dumps(args, default=str)[:500]}")

  # RBAC Validation
  if session_id.startswith("tg_"):
    allowed_tools = ADMIN_TOOLS
  elif session_id.startswith("wa_"):
    allowed_tools = WHATSAPP_TOOLS
  else:
    allowed_tools = PUBLIC_TOOLS
  if not any(t['function']['name'] == tool_name for t in allowed_tools):
    return _tool_return(
      tool_name, tool_call_id,
      f"SECURITY ALERT: Access to tool '{tool_name}' is strictly forbidden for this user. Nice try, hacker!")

  if tool_name == 'calc':
    try:
      ans = calc.do_calc(args['operand1'], args['operand2'], args['operator'])
      return _tool_return(tool_name, tool_call_id, ans)
    except ZeroDivisionError as e:
      return _tool_return(tool_name, tool_call_id, str(e))
    except ValueError as e:
      return _tool_return(tool_name, tool_call_id, str(e))
  elif tool_name == 'searxng_search':
    results = await asyncio.to_thread(searxng_search.search, args['query'], args.get('num_results', 5))
    return _tool_return(tool_name, tool_call_id, results)
  elif tool_name == 'fetch_page':
    content = await asyncio.to_thread(fetch_page.fetch_page_content, args['url'])
    return _tool_return(tool_name, tool_call_id, content)
  elif tool_name == 'check_owner_availability':
    availability = await asyncio.to_thread(google_calendar.check_owner_availability, args.get('time_min'),
                                           args.get('time_max'))
    return _tool_return(tool_name, tool_call_id, availability)
  elif tool_name == 'propose_calendar_event':
    result = await asyncio.to_thread(google_calendar.propose_calendar_event, args.get('summary'), args.get('start_iso'),
                                     args.get('end_iso'), args.get('description', ''),
                                     args.get('requester_id', 'Unknown'))
    return _tool_return(tool_name, tool_call_id, result)
  elif tool_name == 'get_whatsapp_new_messages':
    transcript = await asyncio.to_thread(whatsapp_summary.get_new_messages, args.get('chat_name_query'))
    return _tool_return(tool_name, tool_call_id, transcript)
  elif tool_name == 'get_whatsapp_history':
    history = await asyncio.to_thread(whatsapp_summary.get_chat_history, args.get('chat_name_query'),
                                      args.get('timeframe_hours', 24), args.get('search_text'))
    return _tool_return(tool_name, tool_call_id, history)
  elif tool_name in ('schedule_telegram_reminder', 'schedule_whatsapp_message', 'schedule_whatsapp_summary',
                     'schedule_llm_task'):
    action_map = {
      'schedule_telegram_reminder': 'send_telegram_reminder',
      'schedule_whatsapp_message': 'send_whatsapp_message',
      'schedule_whatsapp_summary': 'send_summary',
      'schedule_llm_task': 'llm_task',
    }
    action = action_map[tool_name]

    # Validate: must have execution_time; cron_expression required if is_recurring is true
    execution_time = args.get('execution_time')
    cron = args.get('cron_expression')
    if not execution_time:
      return _tool_return(tool_name, tool_call_id,
                          "Error: execution_time is required. Cannot schedule a task with no time specified.")
    is_recurring = args.get('is_recurring', False)
    if is_recurring and not cron:
      return _tool_return(tool_name, tool_call_id, "Error: cron_expression is required for recurring tasks.")

    task_id = str(uuid.uuid4())[:8]
    if execution_time:
      try:
        original_time = execution_time
        dt = datetime.datetime.fromisoformat(execution_time)
        if dt.tzinfo is None:
          dt = pytz.timezone('Asia/Singapore').localize(dt)
        execution_time = dt.astimezone(pytz.utc).isoformat()
        logging.info(f"Schedule [{tool_name}]: LLM sent '{original_time}', stored as UTC '{execution_time}'")
      except Exception as e:
        logging.error(f"Error parsing execution_time {execution_time}: {e}")
        return _tool_return(
          tool_name, tool_call_id,
          f"Error: could not parse execution_time '{execution_time}'. Please provide a valid ISO timestamp (e.g., 2025-06-15T09:00:00)."
        )

    # Flatten args into params (drop execution_time and cron_expression)
    params = {k: v for k, v in args.items() if k not in ('execution_time', 'cron_expression')}

    conn = sqlite3.connect(os.path.join(ROOT_DIR, 'whatsapp.db'))
    cursor = conn.cursor()
    cursor.execute(
      "INSERT INTO scheduled_tasks (task_id, owner_id, execution_time, action_type, action_params, cron_expression, status) VALUES (?, ?, ?, ?, ?, ?, ?)",
      (task_id, session_id, execution_time, action, json.dumps(params), cron, 'pending'))
    conn.commit()
    conn.close()

    # Send Telegram confirmation with exact details
    _send_scheduling_confirmation(task_id, action, params, execution_time, cron)

    return _tool_return(tool_name, tool_call_id, f"Task scheduled successfully (ID: {task_id}).")
  elif tool_name == 'list_scheduled_tasks':
    conn = sqlite3.connect(os.path.join(ROOT_DIR, 'whatsapp.db'))
    cursor = conn.cursor()
    cursor.execute(
      "SELECT task_id, execution_time, action_type, action_params FROM scheduled_tasks WHERE status = 'pending'")
    tasks = cursor.fetchall()
    conn.close()
    if not tasks:
      return _tool_return(tool_name, tool_call_id, "No pending scheduled tasks found.")

    output = ["Upcoming Scheduled Tasks:"]
    for t in tasks:
      output.append(f"- {t[0]}: {t[1]} | Action: {t[2]} | Params: {t[3]}")
    return _tool_return(tool_name, tool_call_id, "\n".join(output))
  elif tool_name == 'cancel_scheduled_task':
    task_id = args.get('task_id')
    conn = sqlite3.connect(os.path.join(ROOT_DIR, 'whatsapp.db'))
    cursor = conn.cursor()
    cursor.execute("UPDATE scheduled_tasks SET status = 'cancelled' WHERE task_id = ?", (task_id,))
    conn.commit()
    conn.close()
    return _tool_return(tool_name, tool_call_id, f"Task {task_id} has been cancelled.")
  elif tool_name == 'list_calendar_events':
    events = await asyncio.to_thread(google_calendar.list_calendar_events, args.get('time_min'), args.get('time_max'))
    return _tool_return(tool_name, tool_call_id, events)
  elif tool_name == 'create_calendar_event':
    result = await asyncio.to_thread(google_calendar.create_calendar_event, args.get('calendar_id', 'primary'),
                                     args.get('summary'), args.get('start_iso'), args.get('end_iso'),
                                     args.get('description', ''))
    return _tool_return(tool_name, tool_call_id, result)
  elif tool_name == 'delete_calendar_event':
    result = await asyncio.to_thread(google_calendar.delete_calendar_event, args.get('calendar_id', 'primary'),
                                     args.get('event_id'))
    return _tool_return(tool_name, tool_call_id, result)
  elif tool_name == 'update_calendar_event':
    result = await asyncio.to_thread(google_calendar.update_calendar_event, args.get('calendar_id', 'primary'),
                                     args.get('event_id'), args.get('summary'), args.get('start_iso'),
                                     args.get('end_iso'), args.get('description'))
    return _tool_return(tool_name, tool_call_id, result)
  elif tool_name == 'list_user_calendars':
    calendars = await asyncio.to_thread(google_calendar.list_user_calendars)
    return _tool_return(tool_name, tool_call_id, calendars)
  elif tool_name == 'get_profile':
    profile = await asyncio.to_thread(owner_profile.get_profile)
    return _tool_return(tool_name, tool_call_id, profile)
  elif tool_name == 'update_owner_status':
    result = await asyncio.to_thread(owner_profile.update_owner_status, args.get('key'), args.get('value'))
    return _tool_return(tool_name, tool_call_id, result)
  elif tool_name == 'find_whatsapp_chat':
    name = args.get('name', '')
    conn = sqlite3.connect(os.path.join(ROOT_DIR, 'whatsapp.db'), timeout=10.0)
    cursor = conn.cursor()
    cursor.execute("SELECT chat_id, display_name FROM contacts WHERE display_name LIKE ? ORDER BY last_seen DESC",
                   (f"%{name}%",))
    matches = cursor.fetchall()
    conn.close()
    if not matches:
      return _tool_return(tool_name, tool_call_id, f"No contacts found matching '{name}'.")
    output = [f"Matches for '{name}':"]
    for chat_id, display_name in matches:
      output.append(f"- {display_name} (ID: {chat_id})")
    return _tool_return(tool_name, tool_call_id, "\n".join(output))
  elif tool_name == 'propose_whatsapp_message':
    proposal_id = str(uuid.uuid4())[:8]
    chat_id = args.get('chat_id')
    recipient_name = args.get('recipient_name')
    message_text = args.get('message_text')
    conn = sqlite3.connect(os.path.join(ROOT_DIR, 'whatsapp.db'), timeout=10.0)
    cursor = conn.cursor()
    cursor.execute(
      "INSERT INTO whatsapp_proposals (proposal_id, chat_id, recipient_name, message_text, status) VALUES (?, ?, ?, ?, ?)",
      (proposal_id, chat_id, recipient_name, message_text, 'pending'))
    conn.commit()
    conn.close()
    return _tool_return(tool_name, tool_call_id, f"[Proposal: {proposal_id}]")
  elif tool_name == 'count_pending_messages':
    conn = sqlite3.connect(os.path.join(ROOT_DIR, 'whatsapp.db'), timeout=10.0)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM messages_for_owner WHERE read_status = 'unread'")
    count = cursor.fetchone()[0]
    conn.close()
    return _tool_return(tool_name, tool_call_id, f"You have {count} pending message(s).")
  elif tool_name == 'get_pending_messages':
    conn = sqlite3.connect(os.path.join(ROOT_DIR, 'whatsapp.db'), timeout=10.0)
    cursor = conn.cursor()
    cursor.execute(
      "SELECT id, sender_name, sender_id, chat_name, chat_id, message_text, timestamp, read_status FROM messages_for_owner WHERE read_status = 'unread' ORDER BY timestamp DESC"
    )
    messages = cursor.fetchall()
    conn.close()
    if not messages:
      return _tool_return(tool_name, tool_call_id, "No pending messages for you.")
    output = [f"You have {len(messages)} message(s) waiting:"]
    for msg_id, sender_name, sender_id, chat_name, chat_id, message_text, timestamp, read_status in messages:
      output.append(f"\nMessage #{msg_id}:")
      output.append(f"  From: {sender_name}")
      output.append(f"  Context: {chat_name}")
      output.append(f"  Time: {timestamp}")
      output.append(f"  Message: {message_text}")
    return _tool_return(tool_name, tool_call_id, "\n".join(output))
  elif tool_name == 'clear_messages':
    mode = args.get('mode', 'all')
    conn = sqlite3.connect(os.path.join(ROOT_DIR, 'whatsapp.db'), timeout=10.0)
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
    return _tool_return(tool_name, tool_call_id, f"Cleared {cleared} message(s).")
  elif tool_name == 'check_email_inbox':
    result = await asyncio.to_thread(gmail.check_inbox, args.get('max_results', 10), args.get('query'))
    return _tool_return(tool_name, tool_call_id, result)
  elif tool_name == 'read_email':
    result = await asyncio.to_thread(gmail.read_email, args['message_id'])
    return _tool_return(tool_name, tool_call_id, result)
  elif tool_name == 'mark_emails_read':
    result = await asyncio.to_thread(gmail.mark_emails_read, args['message_ids'])
    return _tool_return(tool_name, tool_call_id, result)
  else:
    return _tool_return(tool_name, tool_call_id, 'Tool doesn\'t exist')


def _get_loaded_model() -> str:
  """Fetch the currently loaded model name from llama.cpp."""
  try:
    resp = requests.get(_MODELS_URL, timeout=2)
    resp.raise_for_status()
    return resp.json()["data"][0]["id"]
  except Exception:
    return ""  # fallback: assume no stripping


def _needs_reasoning_in_history(model_name: str) -> bool:
  """Return True if the model family benefits from seeing prior reasoning."""
  return "qwen" in model_name.lower()


def _strip_reasoning(messages: list) -> list:
  """Return a copy of messages with 'reasoning_content' removed from each."""
  return [{k: v for k, v in msg.items() if k != 'reasoning_content'} for msg in messages]


_MAX_CONTEXT_TOKENS = 32768
_CHARS_PER_TOKEN = 4


def _limit_tokens(messages: list, max_tokens: int = _MAX_CONTEXT_TOKENS) -> list:
  """Trim oldest messages to fit within max_tokens (approximate).

  Always keeps the system prompt (index 0). Evicts complete assistant+tool_result
  exchange pairs from the front so the message list stays valid (no orphaned tool results).
  """
  if len(messages) <= 1:
    return messages

  # Estimate total tokens (skip system prompt from the count)
  def _msg_tokens(msg):
    content = msg.get('content', '') or ''
    # For assistant messages with tool_calls, count the arguments too
    tool_calls = msg.get('tool_calls', [])
    for tc in tool_calls:
      content += json.dumps(tc)
    return len(str(content)) // _CHARS_PER_TOKEN

  # Check if we're already under the limit
  total = sum(_msg_tokens(m) for m in messages[1:])
  if total <= max_tokens:
    return messages

  # Build list of "blocks" to evict. A block is either:
  # - a single user/tool message, or
  # - an assistant tool_call + all subsequent tool results (complete exchange)
  blocks = []  # list of (start_idx, end_idx_exclusive, token_count)
  i = 1  # skip system prompt
  while i < len(messages):
    msg = messages[i]
    if msg.get('role') == 'assistant' and msg.get('tool_calls'):
      # Group assistant tool_call + all following tool results into one block
      block_start = i
      i += 1
      while i < len(messages) and messages[i].get('role') == 'tool':
        i += 1
      block_end = i
      blocks.append((block_start, block_end, sum(_msg_tokens(messages[j]) for j in range(block_start, block_end))))
    else:
      blocks.append((i, i + 1, _msg_tokens(msg)))
      i += 1

  # Evict blocks from the oldest end until under the limit
  total = sum(_msg_tokens(m) for m in messages[1:])
  evict_end = 1  # index up to which messages are kept (exclusive, after system prompt)
  for start, end, tokens in blocks:
    if total <= max_tokens:
      break
    # Evict this block
    evict_end = start
    total -= tokens

  if evict_end <= 1:
    # Keep system prompt + everything we couldn't evict
    return messages

  return [messages[0]] + messages[evict_end:]


async def get_llm_response(session_id, user_input, system_prompt_override=None):
  if session_id not in sessions:
    sessions[session_id] = copy.deepcopy(_STARTER_MESSAGES)

  if system_prompt_override:
    sessions[session_id][0]['content'] = system_prompt_override

  sessions[session_id].append({'role': 'user', 'content': user_input})

  # RBAC: Select tool list based on session ID
  if session_id.startswith("tg_"):
    active_tools = ADMIN_TOOLS
  elif session_id.startswith("wa_"):
    active_tools = WHATSAPP_TOOLS
  else:
    active_tools = PUBLIC_TOOLS

  # Conditionally strip reasoning_content based on loaded model family
  model_name = _get_loaded_model()
  if _needs_reasoning_in_history(model_name):
    payload_messages = sessions[session_id]
  else:
    payload_messages = _strip_reasoning(sessions[session_id])

  # Enforce token budget — trim oldest messages if over limit
  payload_messages = _limit_tokens(payload_messages)

  payload = {
    "messages": payload_messages,
    "stream": False,
    "return_progress": True,
    "reasoning_format": "auto",
    "backend_sampling": False,
    "timings_per_token": True,
    "tools": active_tools,
    "tool_choice": "auto",
  }

  while True:
    try:
      response = requests.post(_URL, json=payload, headers=_HEADERS)
      response.raise_for_status()
      full_resp = response.json()
    except Exception as e:
      logging.error(f"API request failed: {e}")
      return 'Sorry, the LLM API is currently down or unreachable.', None, None

    tool_calls = full_resp['choices'][0]['message'].get('tool_calls', None)

    if tool_calls:
      sessions[session_id].append(full_resp['choices'][0]['message'])
      proposal_output = None
      for tc in tool_calls:
        result_msg = await execute_tool(tc, session_id)
        sessions[session_id].append(result_msg)
        # If propose_whatsapp_message was called, return the tag directly
        if tc['function']['name'] == 'propose_whatsapp_message':
          proposal_output = result_msg['content']
      if proposal_output:
        return proposal_output, None, None
      if _needs_reasoning_in_history(model_name):
        payload["messages"] = sessions[session_id]
      else:
        payload["messages"] = _strip_reasoning(sessions[session_id])
      # Re-apply token limit after tool results were appended
      payload["messages"] = _limit_tokens(payload["messages"])
      continue

    else:
      llama_resp = full_resp['choices'][0]['message']
      sessions[session_id].append(llama_resp)
      pp = full_resp.get('timings', {}).get('prompt_per_second', 0)
      tp = full_resp.get('timings', {}).get('predicted_per_second', 0)
      return llama_resp['content'], pp, tp


def clear_session(session_id):
  if session_id in sessions:
    del sessions[session_id]
