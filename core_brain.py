import asyncio
import copy
import json
import os

import requests
from absl import logging
from requests.exceptions import HTTPError, JSONDecodeError, RequestException

import tools.calc as calc
import tools.fetch_page as fetch_page
import tools.gmail as gmail
import tools.google_calendar as google_calendar
import tools.owner_profile as owner_profile
import tools.searxng_search as searxng_search
import tools.whatsapp_summary as whatsapp_summary
import util.config as config
import util.db_tools as db_tools
import util.scheduling as scheduling
from tools.tool_definitions import ADMIN_TOOLS, PUBLIC_TOOLS, WHATSAPP_TOOLS

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))

_CFG = config.load_config()
_BASE_URL = _CFG.get('llm', {}).get('base_url', 'http://localhost:8080')
_URL = f"{_BASE_URL}/v1/chat/completions"
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


# ---------------------------------------------------------------------------
# Tool-call parsing and RBAC helpers (pure functions, easily testable)
# ---------------------------------------------------------------------------


def _parse_tool_call(tc):
  """Extract (tool_call_id, tool_name, args) from a tool call dict."""
  tool_call_id = tc['id']
  tool_name = tc['function']['name']
  args = json.loads(tc['function']['arguments'])
  return tool_call_id, tool_name, args


def _get_allowed_tools(session_id):
  """Return the allowed tool list based on session_id prefix (RBAC)."""
  if session_id.startswith("tg_"):
    return ADMIN_TOOLS
  elif session_id.startswith("wa_"):
    return WHATSAPP_TOOLS
  return PUBLIC_TOOLS


def _validate_tool_access(tool_name, allowed_tools):
  """Check if tool_name is in the allowed tools list. Returns True/False."""
  return any(t['function']['name'] == tool_name for t in allowed_tools)


# ---------------------------------------------------------------------------
# Thin handler dispatchers for tool groups that delegate to external modules
# ---------------------------------------------------------------------------


async def _handle_basic_tools(tool_name, args):
  """Handle calc, searxng_search, fetch_page. Returns result string or None."""
  if tool_name == 'calc':
    try:
      ans = calc.do_calc(args['operand1'], args['operand2'], args['operator'])
      return ans
    except (ZeroDivisionError, ValueError) as e:
      return str(e)
  elif tool_name == 'searxng_search':
    results = await asyncio.to_thread(searxng_search.search, args['query'], args.get('num_results', 5))
    return results
  elif tool_name == 'fetch_page':
    content = await asyncio.to_thread(fetch_page.fetch_page_content, args['url'])
    return content
  return None


async def _handle_whatsapp_message_tools(tool_name, args):
  """Handle get_whatsapp_new_messages, get_whatsapp_history. Returns result string or None."""
  if tool_name == 'get_whatsapp_new_messages':
    transcript = await asyncio.to_thread(whatsapp_summary.get_new_messages, args.get('chat_name_query'))
    return transcript
  elif tool_name == 'get_whatsapp_history':
    history = await asyncio.to_thread(whatsapp_summary.get_chat_history, args.get('chat_name_query'),
                                      args.get('timeframe_hours', 24), args.get('search_text'))
    return history
  return None


async def _handle_calendar_tools(tool_name, args):
  """Handle all calendar tools. Returns result string or None."""
  if tool_name == 'check_owner_availability':
    return await asyncio.to_thread(google_calendar.check_owner_availability, args.get('time_min'), args.get('time_max'))
  elif tool_name == 'propose_calendar_event':
    return await asyncio.to_thread(google_calendar.propose_calendar_event, args.get('summary'), args.get('start_iso'),
                                   args.get('end_iso'), args.get('description', ''),
                                   args.get('requester_id', 'Unknown'))
  elif tool_name == 'list_calendar_events':
    return await asyncio.to_thread(google_calendar.list_calendar_events, args.get('time_min'), args.get('time_max'))
  elif tool_name == 'create_calendar_event':
    return await asyncio.to_thread(google_calendar.create_calendar_event, args.get('calendar_id', 'primary'),
                                   args.get('summary'), args.get('start_iso'), args.get('end_iso'),
                                   args.get('description', ''))
  elif tool_name == 'delete_calendar_event':
    return await asyncio.to_thread(google_calendar.delete_calendar_event, args.get('calendar_id', 'primary'),
                                   args.get('event_id'))
  elif tool_name == 'update_calendar_event':
    return await asyncio.to_thread(google_calendar.update_calendar_event, args.get('calendar_id', 'primary'),
                                   args.get('event_id'), args.get('summary'), args.get('start_iso'),
                                   args.get('end_iso'), args.get('description'))
  elif tool_name == 'list_user_calendars':
    return await asyncio.to_thread(google_calendar.list_user_calendars)
  return None


async def _handle_profile_tools(tool_name, args):
  """Handle get_profile, update_owner_status. Returns result string or None."""
  if tool_name == 'get_profile':
    return await asyncio.to_thread(owner_profile.get_profile)
  elif tool_name == 'update_owner_status':
    return await asyncio.to_thread(owner_profile.update_owner_status, args.get('key'), args.get('value'))
  return None


async def _handle_email_tools(tool_name, args):
  """Handle check_email_inbox, read_email, mark_emails_read. Returns result string or None."""
  if tool_name == 'check_email_inbox':
    return await asyncio.to_thread(gmail.check_inbox, args.get('max_results', 10), args.get('query'))
  elif tool_name == 'read_email':
    return await asyncio.to_thread(gmail.read_email, args['message_id'])
  elif tool_name == 'mark_emails_read':
    return await asyncio.to_thread(gmail.mark_emails_read, args['message_ids'])
  return None


# ---------------------------------------------------------------------------
# Main tool dispatcher
# ---------------------------------------------------------------------------


async def execute_tool(tc, session_id):
  tool_call_id, tool_name, args = _parse_tool_call(tc)
  logging.info(f"TOOL CALL: {tool_name} args={json.dumps(args, default=str)[:500]}")

  allowed_tools = _get_allowed_tools(session_id)
  if not _validate_tool_access(tool_name, allowed_tools):
    return _tool_return(
      tool_name, tool_call_id,
      f"SECURITY ALERT: Access to tool '{tool_name}' is strictly forbidden for this user. Nice try, hacker!")

  db_path = os.path.join(ROOT_DIR, 'whatsapp.db')

  # Try each handler; first non-None result wins
  for handler in [
      lambda: _handle_basic_tools(tool_name, args),
      lambda: _handle_whatsapp_message_tools(tool_name, args),
      lambda: scheduling.handle_schedule_task(tool_name, args, session_id, db_path),
      lambda: scheduling.handle_list_scheduled_tasks(db_path) if tool_name == 'list_scheduled_tasks' else None,
      lambda: scheduling.handle_cancel_scheduled_task(args, db_path) if tool_name == 'cancel_scheduled_task' else None,
      lambda: _handle_calendar_tools(tool_name, args),
      lambda: _handle_profile_tools(tool_name, args),
      lambda: _handle_email_tools(tool_name, args),
      lambda: db_tools.handle_find_whatsapp_chat(args, db_path) if tool_name == 'find_whatsapp_chat' else None,
      lambda: db_tools.handle_propose_whatsapp_message(args, db_path)
      if tool_name == 'propose_whatsapp_message' else None,
      lambda: db_tools.handle_count_pending_messages(db_path) if tool_name == 'count_pending_messages' else None,
      lambda: db_tools.handle_get_pending_messages(db_path) if tool_name == 'get_pending_messages' else None,
      lambda: db_tools.handle_clear_messages(args, db_path) if tool_name == 'clear_messages' else None,
  ]:
    result = handler()
    if asyncio.iscoroutine(result):
      result = await result
    if result is not None:
      return _tool_return(tool_name, tool_call_id, result)

  return _tool_return(tool_name, tool_call_id, 'Tool doesn\'t exist')


# ---------------------------------------------------------------------------
# LLM interaction
# ---------------------------------------------------------------------------

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
    if isinstance(content, list):
      # Multi-part (vision) content — estimate tokens from text + image overhead
      text_parts = ''.join(p.get('text', '') for p in content if p.get('type') == 'text')
      image_count = sum(1 for p in content if p.get('type') == 'image_url')
      # ~768 tokens per image (standard vision model tile cost)
      content = text_parts + 'x' * (image_count * 768 * 4)
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
  for start, _end, tokens in blocks:
    if total <= max_tokens:
      break
    # Evict this block
    evict_end = start
    total -= tokens

  if evict_end <= 1:
    # Keep system prompt + everything we couldn't evict
    return messages

  return [messages[0]] + messages[evict_end:]


async def get_llm_response(session_id, user_input, system_prompt_override=None, images=None):
  if session_id not in sessions:
    sessions[session_id] = copy.deepcopy(_STARTER_MESSAGES)

  if system_prompt_override:
    sessions[session_id][0]['content'] = system_prompt_override

  if images:
    content_parts = [{"type": "text", "text": user_input}]
    for img_b64, mime in images:
      content_parts.append({
        "type": "image_url",
        "image_url": {
          "url": f"data:{mime};base64,{img_b64}"
        },
      })
    sessions[session_id].append({"role": "user", "content": content_parts})
  else:
    sessions[session_id].append({'role': 'user', 'content': user_input})

  # RBAC: Select tool list based on session ID
  if session_id.startswith("tg_"):
    active_tools = ADMIN_TOOLS
  elif session_id.startswith("wa_"):
    active_tools = WHATSAPP_TOOLS
  else:
    active_tools = PUBLIC_TOOLS

  payload_messages = sessions[session_id]

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
    except HTTPError as e:
      # Graceful failure if the LLM server doesn't support vision.
      # HTTPError is only raised for non-2xx, so check if the last user
      # message in this payload carries images.
      last_user_msg = next(
        (m for m in reversed(payload["messages"]) if m.get("role") == "user"),
        None,
      )
      if last_user_msg and isinstance(last_user_msg.get("content"), list):
        has_images = any(p.get("type") == "image_url" for p in last_user_msg["content"])
        if has_images:
          sessions[session_id].pop()  # remove the failed multi-part message
          raise RuntimeError("Image processing is not supported by the LLM server right now. "
                             "Please try sending text instead.") from e
      logging.error(f"API request failed: {e}")
      raise RuntimeError(f"API request failed: {e}") from e
    except (RequestException, JSONDecodeError) as e:
      logging.error(f"API request failed: {e}")
      raise RuntimeError(f"API request failed: {e}") from e

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
      payload["messages"] = sessions[session_id]
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
