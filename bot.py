import asyncio
import logging as py_logging
import os
import re

import requests
from absl import app, logging
from absl import logging as absl_logging
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ApplicationBuilder, CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler, filters

import core_brain
import scheduler_manager
import tools.google_calendar as google_calendar
import tools.notes as notes
import util.config as config
import util.get_health as get_health
import util.get_time as get_time
from util import db_tools
from util.message import compose_long_message

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))

_TOKEN_FILE = 'token'
show_tps = False


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
  await context.bot.send_message(chat_id=update.effective_chat.id, text="Hello from bot")


async def note(update: Update, context: ContextTypes.DEFAULT_TYPE):
  if not context.args:
    await context.bot.send_message(
      chat_id=update.effective_chat.id,
      text="Usage: /note <your note>",
    )
    return
  text = ' '.join(context.args)
  try:
    notes.save_note(text)
    await context.bot.send_message(
      chat_id=update.effective_chat.id,
      text="✅ Note saved.",
    )
  except PermissionError:
    await context.bot.send_message(
      chat_id=update.effective_chat.id,
      text="❌ Can't save note — permission denied. Check the notes file path in config.yaml.",
    )
  except (FileNotFoundError, OSError) as e:
    await context.bot.send_message(
      chat_id=update.effective_chat.id,
      text=f"❌ Can't save note — {e}",
    )
  except Exception as e:
    logging.error("Unexpected error saving note: %s", e, exc_info=True)
    await context.bot.send_message(
      chat_id=update.effective_chat.id,
      text="❌ Something went wrong saving your note. Check the logs.",
    )


async def tps(update: Update, context: ContextTypes.DEFAULT_TYPE):
  global show_tps
  show_tps = not show_tps
  await context.bot.send_message(chat_id=update.effective_chat.id, text=f'Show tps: {show_tps}')


async def health(update: Update, context: ContextTypes.DEFAULT_TYPE):
  stats = get_health.get_system_stats()
  await context.bot.send_message(chat_id=update.effective_chat.id, text=stats)


async def clear_context(update: Update, context: ContextTypes.DEFAULT_TYPE):
  session_id = f"tg_{update.effective_chat.id}"
  core_brain.clear_session(session_id)
  await context.bot.send_message(chat_id=update.effective_chat.id, text='Context cleared.')


async def wa_on(update: Update, context: ContextTypes.DEFAULT_TYPE):
  cfg = config.load_config()
  cfg.setdefault('whatsapp', {}).setdefault('autoresponder', {})['enabled'] = True
  config.save_config(cfg)
  await context.bot.send_message(chat_id=update.effective_chat.id, text="✅ WhatsApp autoresponder is now ON.")


async def wa_off(update: Update, context: ContextTypes.DEFAULT_TYPE):
  cfg = config.load_config()
  cfg.setdefault('whatsapp', {}).setdefault('autoresponder', {})['enabled'] = False
  config.save_config(cfg)
  await context.bot.send_message(chat_id=update.effective_chat.id, text="❌ WhatsApp autoresponder is now OFF.")


async def wa_groups(update: Update, context: ContextTypes.DEFAULT_TYPE):
  cfg = config.load_config()
  allowed = cfg.get('whatsapp', {}).get('autoresponder', {}).get('allowed_groups', [])
  if not allowed:
    await context.bot.send_message(chat_id=update.effective_chat.id, text="No groups configured for autoresponse.")
    return
  # Try to resolve group names from contacts
  lines = ["Allowed groups for autoresponse:"]
  db_path = os.path.join(ROOT_DIR, 'whatsapp.db')
  for gid in allowed:
    name = db_tools.get_contact_by_chat_id(gid, db_path) or gid
    lines.append(f"- {name} ({gid})")
  await context.bot.send_message(chat_id=update.effective_chat.id, text="\n".join(lines))


async def wa_group_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
  if not context.args:
    await context.bot.send_message(chat_id=update.effective_chat.id, text="Usage: /wa_group_add <group_name>")
    return
  group_query = ' '.join(context.args)
  # Resolve group name to chatId using contacts table
  matches = db_tools.search_contacts_by_name(group_query, os.path.join(ROOT_DIR, 'whatsapp.db'))
  if not matches:
    await context.bot.send_message(
      chat_id=update.effective_chat.id,
      text=f"No groups found matching '{group_query}'. Make sure the group has had recent activity.")
    return
  if len(matches) > 1:
    lines = [f"Multiple groups match '{group_query}':"]
    for chat_id, name in matches:
      lines.append(f"- {name} ({chat_id})")
    lines.append("Be more specific or use the exact chat ID.")
    await context.bot.send_message(chat_id=update.effective_chat.id, text="\n".join(lines))
    return
  chat_id, display_name = matches[0]
  cfg = config.load_config()
  wa = cfg.setdefault('whatsapp', {}).setdefault('autoresponder', {})
  allowed = wa.setdefault('allowed_groups', [])
  if chat_id not in allowed:
    allowed.append(chat_id)
    config.save_config(cfg)
    await context.bot.send_message(
      chat_id=update.effective_chat.id, text=f"✅ Added '{display_name}' to allowed groups.")
  else:
    await context.bot.send_message(
      chat_id=update.effective_chat.id, text=f"'{display_name}' is already in the allowed list.")


async def wa_group_remove(update: Update, context: ContextTypes.DEFAULT_TYPE):
  if not context.args:
    await context.bot.send_message(chat_id=update.effective_chat.id, text="Usage: /wa_group_remove <group_name>")
    return
  group_query = ' '.join(context.args)
  cfg = config.load_config()
  allowed = cfg.get('whatsapp', {}).get('autoresponder', {}).get('allowed_groups', [])
  # Try exact match first, then partial name match via contacts
  removed = None
  if group_query in allowed:
    removed = group_query
  else:
    removed = db_tools.find_contact_in_allowed(group_query, allowed, os.path.join(ROOT_DIR, 'whatsapp.db'))
  if removed and removed in allowed:
    allowed.remove(removed)
    cfg.setdefault('whatsapp', {}).setdefault('autoresponder', {})['allowed_groups'] = allowed
    config.save_config(cfg)
    await context.bot.send_message(chat_id=update.effective_chat.id, text="✅ Removed group from allowed list.")
  else:
    await context.bot.send_message(
      chat_id=update.effective_chat.id, text=f"No matching group found in allowed list for '{group_query}'.")


async def wa_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
  filter_type = ' '.join(context.args) if context.args else ''

  if filter_type.lower() == 'groups' or filter_type.lower() == 'group':
    title = "WhatsApp Groups"
  elif filter_type.lower() == 'private' or filter_type.lower() == 'people':
    title = "WhatsApp Private Chats"
  else:
    title = "All WhatsApp Contacts"

  rows = db_tools.list_contacts(os.path.join(ROOT_DIR, 'whatsapp.db'), filter_type)

  if not rows:
    await context.bot.send_message(chat_id=update.effective_chat.id, text="No contacts found.")
    return

  lines = [f"{title}:"]
  for name, chat_id in rows:
    lines.append(f"- {name} ({chat_id})")
  await context.bot.send_message(chat_id=update.effective_chat.id, text="\n".join(lines))


async def handle_event_proposal(update: Update, context: ContextTypes.DEFAULT_TYPE):
  query = update.callback_query
  await query.answer()

  db_path = os.path.join(ROOT_DIR, 'whatsapp.db')
  data = query.data
  if data.startswith("app_"):
    proposal_id = data[4:]
    row = db_tools.get_event_proposal(proposal_id, db_path)

    if row:
      summary, start, end, desc, req_id = row
      result = google_calendar.create_calendar_event(summary=summary, start_iso=start, end_iso=end, description=desc)
      await query.edit_message_text(text=f"✅ Event approved and created!\n\n{result}")
      db_tools.update_event_proposal_status(proposal_id, 'approved', db_path)
    else:
      await query.edit_message_text(text="Error: Proposal not found.")

  elif data.startswith("rej_"):
    proposal_id = data[4:]
    db_tools.update_event_proposal_status(proposal_id, 'rejected', db_path)
    await query.edit_message_text(text="❌ Event request rejected.")

  elif data.startswith("wa_send_"):
    proposal_id = data[8:]
    row = db_tools.get_whatsapp_proposal(proposal_id, db_path)

    if not row:
      await query.edit_message_text(text="Error: Proposal not found.", reply_markup=None)
      return

    chat_id, recipient_name, message_text, status = row
    if status != 'pending':
      await query.edit_message_text(text="This proposal was already processed.", reply_markup=None)
      return

    # Send the message via WhatsApp gateway
    try:
      resp = requests.post('http://localhost:3000/send-message', json={"chatId": chat_id, "text": f"🤖 {message_text}"})
      if resp.status_code == 200:
        db_tools.update_whatsapp_proposal_status(proposal_id, 'sent', db_path)
        await query.edit_message_text(text=f"✅ Message sent to {recipient_name}!", reply_markup=None)
      else:
        await query.edit_message_text(text=f"❌ Failed to send message: {resp.text}", reply_markup=None)
    except Exception as e:
      await query.edit_message_text(text=f"❌ Error sending message: {e}", reply_markup=None)

  elif data.startswith("wa_cancel_"):
    proposal_id = data[10:]
    db_tools.update_whatsapp_proposal_status(proposal_id, 'cancelled', db_path)
    await query.edit_message_text(text="❌ Message cancelled.", reply_markup=None)


async def _send_error_message(context, chat_id):
  await context.bot.send_message(
    chat_id=chat_id,
    text="Sorry, I encountered an error processing your request.",
  )


async def msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
  session_id = f"tg_{update.effective_chat.id}"
  cur_time = get_time.get_current_time_with_timezone()
  content = f'[Context: Current time is {cur_time}]\n\n{update.message.text}'

  try:
    llama_resp, pp, tp = await core_brain.get_llm_response(session_id, content)
    llama_resp, reply_markup = _handle_whatsapp_proposal(llama_resp)
    for text, entities, markup in compose_long_message(llama_resp, show_tps, pp, tp, reply_markup=reply_markup):
      await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=text,
        entities=entities,
        reply_markup=markup,
      )
  except RuntimeError as e:
    logging.error(e)
    await _send_error_message(context, update.effective_chat.id)


def _handle_whatsapp_proposal(markdown_text):
  """Check for a [Proposal: <id>] tag, fetch DB details, clean the text.

  Returns (cleaned_text, reply_markup).
  reply_markup is None if no proposal tag is found.
  """
  match = re.search(r'\[Proposal:\s*(\w+)\]', markdown_text)
  if not match:
    return markdown_text, None

  proposal_id = match.group(1)
  cleaned = re.sub(r'\s*\[Proposal:\s*\w+\]', '', markdown_text).strip()

  try:
    proposal_details = db_tools.get_whatsapp_proposal(proposal_id, os.path.join(ROOT_DIR, 'whatsapp.db'))
    if proposal_details:
      _, recipient_name, message_text, _ = proposal_details
      cleaned = (f"{cleaned}\n\n"
                 f"—\n"
                 f"📨 Pending WhatsApp Message\n"
                 f"To: {recipient_name}\n"
                 f"Message:\n> {message_text}")
  except RuntimeError as e:
    logging.error(f"Error fetching proposal {proposal_id}: {e}")
    raise RuntimeError(f"Error fetching proposal {proposal_id}: {e}") from e

  keyboard = InlineKeyboardMarkup([[
    InlineKeyboardButton("✅ Send", callback_data=f"wa_send_{proposal_id}"),
    InlineKeyboardButton("❌ Cancel", callback_data=f"wa_cancel_{proposal_id}")
  ]])
  return cleaned, keyboard


def fetch_token():
  with open(_TOKEN_FILE) as f:
    token = f.read().strip()
  return token


async def post_init(application):
  cfg = config.load_config()
  owner_id = cfg.get('owner', {}).get('chat_id', '')
  asyncio.create_task(scheduler_manager.scheduler_loop(application.bot, owner_id))


def _log_llm_server_status():
  """Check LLM server and log URL + model name. Non-fatal if unreachable."""
  cfg = config.load_config()
  base_url = cfg.get('llm', {}).get('base_url', 'http://localhost:8080')

  try:
    resp = requests.get(f"{base_url}/v1/models", timeout=3)
    resp.raise_for_status()
    model = resp.json()["data"][0]["id"]
    logging.info(f"LLM server: {base_url} — model: {model}")
  except Exception as e:
    logging.warning(f"LLM server unreachable at {base_url}: {e}")


def main(argv):
  del argv

  # Enable file logging via Python logging bridge
  absl_logging.use_python_logging()
  file_handler = py_logging.FileHandler(os.path.join(ROOT_DIR, 'tuppo.log'), mode='a', encoding='utf-8')
  file_handler.setFormatter(
    py_logging.Formatter('%(asctime)s | %(levelname)-5s | %(message)s', datefmt='%Y-%m-%d %H:%M:%S'))
  py_logging.getLogger().addHandler(file_handler)

  _log_llm_server_status()
  token = fetch_token()
  application = ApplicationBuilder().token(token).post_init(post_init).build()
  start_handler = CommandHandler('start', start)
  tps_handler = CommandHandler('tps', tps)
  clear_context_handler = CommandHandler('clear_context', clear_context)
  note_handler = CommandHandler('note', note)
  wa_on_handler = CommandHandler('wa_on', wa_on)
  wa_off_handler = CommandHandler('wa_off', wa_off)
  wa_groups_handler = CommandHandler('wa_groups', wa_groups)
  wa_group_add_handler = CommandHandler('wa_group_add', wa_group_add)
  wa_group_remove_handler = CommandHandler('wa_group_remove', wa_group_remove)
  wa_list_handler = CommandHandler('wa_list', wa_list)
  msg_handler = MessageHandler(filters.TEXT & (~filters.COMMAND), msg)
  health_handler = CommandHandler('health', health)
  proposal_handler = CallbackQueryHandler(handle_event_proposal)
  application.add_handler(start_handler)
  application.add_handler(tps_handler)
  application.add_handler(health_handler)
  application.add_handler(msg_handler)
  application.add_handler(clear_context_handler)
  application.add_handler(note_handler)
  application.add_handler(wa_on_handler)
  application.add_handler(wa_off_handler)
  application.add_handler(wa_groups_handler)
  application.add_handler(wa_group_add_handler)
  application.add_handler(wa_group_remove_handler)
  application.add_handler(wa_list_handler)
  application.add_handler(proposal_handler)
  application.run_polling()


if __name__ == '__main__':
  app.run(main)
