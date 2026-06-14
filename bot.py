import asyncio
import os
import re
import sqlite3
import requests
import util.get_time as get_time
import util.get_health as get_health
import core_brain
import telegramify_markdown as tm
from absl import app
from absl import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, filters, CallbackQueryHandler
import scheduler_manager

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))

_TOKEN_FILE = 'token'
show_tps = False


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
  await context.bot.send_message(chat_id=update.effective_chat.id, text="Hello from bot")


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
  import util.config as config
  cfg = config.load_config()
  cfg.setdefault('whatsapp', {}).setdefault('autoresponder', {})['enabled'] = True
  config.save_config(cfg)
  await context.bot.send_message(chat_id=update.effective_chat.id, text="✅ WhatsApp autoresponder is now ON.")


async def wa_off(update: Update, context: ContextTypes.DEFAULT_TYPE):
  import util.config as config
  cfg = config.load_config()
  cfg.setdefault('whatsapp', {}).setdefault('autoresponder', {})['enabled'] = False
  config.save_config(cfg)
  await context.bot.send_message(chat_id=update.effective_chat.id, text="❌ WhatsApp autoresponder is now OFF.")


async def wa_groups(update: Update, context: ContextTypes.DEFAULT_TYPE):
  import util.config as config
  cfg = config.load_config()
  allowed = cfg.get('whatsapp', {}).get('autoresponder', {}).get('allowed_groups', [])
  if not allowed:
    await context.bot.send_message(chat_id=update.effective_chat.id, text="No groups configured for autoresponse.")
    return
  # Try to resolve group names from contacts
  import sqlite3
  conn = sqlite3.connect(os.path.join(ROOT_DIR, 'whatsapp.db'), timeout=10.0)
  cursor = conn.cursor()
  lines = ["Allowed groups for autoresponse:"]
  for gid in allowed:
    cursor.execute("SELECT display_name FROM contacts WHERE chat_id = ?", (gid,))
    row = cursor.fetchone()
    name = row[0] if row else gid
    lines.append(f"- {name} ({gid})")
  conn.close()
  await context.bot.send_message(chat_id=update.effective_chat.id, text="\n".join(lines))


async def wa_group_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
  import sqlite3
  if not context.args:
    await context.bot.send_message(chat_id=update.effective_chat.id, text="Usage: /wa_group_add <group_name>")
    return
  group_query = ' '.join(context.args)
  # Resolve group name to chatId using contacts table
  conn = sqlite3.connect(os.path.join(ROOT_DIR, 'whatsapp.db'), timeout=10.0)
  cursor = conn.cursor()
  cursor.execute("SELECT chat_id, display_name FROM contacts WHERE display_name LIKE ?", (f"%{group_query}%",))
  matches = cursor.fetchall()
  conn.close()
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
  import util.config as config
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
  import util.config as config
  import sqlite3
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
    conn = sqlite3.connect(os.path.join(ROOT_DIR, 'whatsapp.db'), timeout=10.0)
    cursor = conn.cursor()
    if allowed:
      placeholders = ','.join('?' * len(allowed))
      cursor.execute(f"SELECT chat_id FROM contacts WHERE display_name LIKE ? AND chat_id IN ({placeholders})",
                     (f"%{group_query}%",) + tuple(allowed))
      row = cursor.fetchone()
    else:
      row = None
    conn.close()
    if row:
      removed = row[0]
  if removed and removed in allowed:
    allowed.remove(removed)
    cfg.setdefault('whatsapp', {}).setdefault('autoresponder', {})['allowed_groups'] = allowed
    config.save_config(cfg)
    await context.bot.send_message(chat_id=update.effective_chat.id, text="✅ Removed group from allowed list.")
  else:
    await context.bot.send_message(
      chat_id=update.effective_chat.id, text=f"No matching group found in allowed list for '{group_query}'.")


async def wa_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
  import sqlite3
  conn = sqlite3.connect(os.path.join(ROOT_DIR, 'whatsapp.db'), timeout=10.0)
  cursor = conn.cursor()
  filter_type = ' '.join(context.args) if context.args else ''

  if filter_type.lower() == 'groups' or filter_type.lower() == 'group':
    cursor.execute("SELECT display_name, chat_id FROM contacts WHERE chat_id LIKE '%@g.us' ORDER BY display_name")
    title = "WhatsApp Groups"
  elif filter_type.lower() == 'private' or filter_type.lower() == 'people':
    cursor.execute(
      "SELECT display_name, chat_id FROM contacts WHERE chat_id NOT LIKE '%@g.us' AND chat_id != 'status@broadcast' ORDER BY display_name"
    )
    title = "WhatsApp Private Chats"
  else:
    cursor.execute(
      "SELECT display_name, chat_id FROM contacts WHERE chat_id != 'status@broadcast' ORDER BY display_name")
    title = "All WhatsApp Contacts"

  rows = cursor.fetchall()
  conn.close()

  if not rows:
    await context.bot.send_message(chat_id=update.effective_chat.id, text="No contacts found.")
    return

  lines = [f"{title}:"]
  for name, chat_id in rows:
    lines.append(f"- {name} ({chat_id})")
  await context.bot.send_message(chat_id=update.effective_chat.id, text="\n".join(lines))


async def handle_event_proposal(update: Update, context: ContextTypes.DEFAULT_TYPE):
  import sqlite3
  import tools.google_calendar as google_calendar

  query = update.callback_query
  await query.answer()

  data = query.data
  if data.startswith("app_"):
    proposal_id = data[4:]
    conn = sqlite3.connect(os.path.join(ROOT_DIR, 'whatsapp.db'))
    cursor = conn.cursor()
    cursor.execute(
      "SELECT summary, start_iso, end_iso, description, requester_id FROM event_proposals WHERE proposal_id = ?",
      (proposal_id,))
    row = cursor.fetchone()
    conn.close()

    if row:
      summary, start, end, desc, req_id = row
      result = google_calendar.create_calendar_event(summary=summary, start_iso=start, end_iso=end, description=desc)
      await query.edit_message_text(text=f"✅ Event approved and created!\n\n{result}")

      conn = sqlite3.connect(os.path.join(ROOT_DIR, 'whatsapp.db'))
      cursor = conn.cursor()
      cursor.execute("UPDATE event_proposals SET status = 'approved' WHERE proposal_id = ?", (proposal_id,))
      conn.commit()
      conn.close()
    else:
      await query.edit_message_text(text="Error: Proposal not found.")

  elif data.startswith("rej_"):
    proposal_id = data[4:]
    conn = sqlite3.connect(os.path.join(ROOT_DIR, 'whatsapp.db'))
    cursor = conn.cursor()
    cursor.execute("UPDATE event_proposals SET status = 'rejected' WHERE proposal_id = ?", (proposal_id,))
    conn.commit()
    conn.close()
    await query.edit_message_text(text="❌ Event request rejected.")

  elif data.startswith("wa_send_"):
    proposal_id = data[8:]
    conn = sqlite3.connect(os.path.join(ROOT_DIR, 'whatsapp.db'), timeout=10.0)
    cursor = conn.cursor()
    cursor.execute("SELECT chat_id, recipient_name, message_text, status FROM whatsapp_proposals WHERE proposal_id = ?",
                   (proposal_id,))
    row = cursor.fetchone()
    conn.close()

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
        cursor = sqlite3.connect(os.path.join(ROOT_DIR, 'whatsapp.db'), timeout=10.0).cursor()
        cursor.execute("UPDATE whatsapp_proposals SET status = 'sent' WHERE proposal_id = ?", (proposal_id,))
        cursor.connection.commit()
        cursor.connection.close()
        await query.edit_message_text(text=f"✅ Message sent to {recipient_name}!", reply_markup=None)
      else:
        await query.edit_message_text(text=f"❌ Failed to send message: {resp.text}", reply_markup=None)
    except Exception as e:
      await query.edit_message_text(text=f"❌ Error sending message: {e}", reply_markup=None)

  elif data.startswith("wa_cancel_"):
    proposal_id = data[10:]
    conn = sqlite3.connect(os.path.join(ROOT_DIR, 'whatsapp.db'), timeout=10.0)
    cursor = conn.cursor()
    cursor.execute("UPDATE whatsapp_proposals SET status = 'cancelled' WHERE proposal_id = ?", (proposal_id,))
    conn.commit()
    conn.close()
    await query.edit_message_text(text="❌ Message cancelled.", reply_markup=None)


async def msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
  session_id = f"tg_{update.effective_chat.id}"
  cur_time = get_time.get_current_time_with_timezone()
  content = f'[Context: Current time is {cur_time}]\n\n{update.message.text}'

  llama_resp, pp, tp = await core_brain.get_llm_response(session_id, content)

  if llama_resp:
    await send_long_message(context, update.effective_chat.id, llama_resp, pp, tp)
  else:
    await context.bot.send_message(
      chat_id=update.effective_chat.id,
      text="Sorry, I encountered an error processing your request.",
    )


async def send_long_message(context, chat_id, markdown_text, pp=None, tp=None):
  chunks = split_markdown(markdown_text, max_len=3500)
  for i, chunk in enumerate(chunks):
    chat_response, entities = tm.convert(chunk)
    if i == len(chunks) - 1 and show_tps and pp is not None and tp is not None:
      chat_response = f'{chat_response} (pp: {round(pp,2)}, tp: {round(tp,2)})'

    # Check for WhatsApp message proposal tag
    proposal_match = re.search(r'\[Proposal:\s*(\w+)\]', chat_response)
    reply_markup = None
    if proposal_match:
      proposal_id = proposal_match.group(1)
      # Strip the tag from the visible text
      chat_response = re.sub(r'\s*\[Proposal:\s*\w+\]', '', chat_response).strip()

      # Fetch exact proposal details from DB for coded confirmation
      try:
        conn = sqlite3.connect(os.path.join(ROOT_DIR, 'whatsapp.db'), timeout=10.0)
        cursor = conn.cursor()
        cursor.execute("SELECT recipient_name, message_text FROM whatsapp_proposals WHERE proposal_id = ?",
                       (proposal_id,))
        row = cursor.fetchone()
        conn.close()
        if row:
          recipient_name, message_text = row
          chat_response = (f"{chat_response}\n\n"
                           f"—\n"
                           f"📨 Pending WhatsApp Message\n"
                           f"To: {recipient_name}\n"
                           f"Message:\n> {message_text}")
      except Exception as e:
        logging.error(f"Error fetching proposal {proposal_id}: {e}")

      keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Send", callback_data=f"wa_send_{proposal_id}"),
        InlineKeyboardButton("❌ Cancel", callback_data=f"wa_cancel_{proposal_id}")
      ]])
      reply_markup = keyboard

    if chat_response.strip():
      await context.bot.send_message(
        chat_id=chat_id,
        text=chat_response,
        entities=[e.to_dict() for e in entities],
        reply_markup=reply_markup,
      )


def split_markdown(text, max_len=3500):
  if len(text) <= max_len:
    return [text]

  chunks = []
  current_chunk = []
  current_len = 0

  paragraphs = text.split('\n\n')
  for p in paragraphs:
    if len(p) > max_len:
      if current_chunk:
        chunks.append('\n\n'.join(current_chunk))
        current_chunk = []
        current_len = 0

      lines = p.split('\n')
      for line in lines:
        if len(line) > max_len:
          if current_chunk:
            chunks.append('\n'.join(current_chunk))
            current_chunk = []
            current_len = 0
          for i in range(0, len(line), max_len):
            chunks.append(line[i:i + max_len])
        else:
          if current_len + len(line) + 1 > max_len:
            chunks.append('\n'.join(current_chunk))
            current_chunk = [line]
            current_len = len(line)
          else:
            current_chunk.append(line)
            current_len += len(line) + 1
    else:
      if current_len + len(p) + 2 > max_len:
        if current_chunk:
          chunks.append('\n\n'.join(current_chunk))
        current_chunk = [p]
        current_len = len(p)
      else:
        current_chunk.append(p)
        current_len += len(p) + 2

  if current_chunk:
    chunks.append('\n\n'.join(current_chunk))

  return chunks


def fetch_token():
  with open(_TOKEN_FILE, 'r') as f:
    token = f.read().strip()
  return token


async def post_init(application):
  import util.config as config
  cfg = config.load_config()
  owner_id = cfg.get('owner', {}).get('chat_id', '')
  asyncio.create_task(scheduler_manager.scheduler_loop(application.bot, owner_id))


def _log_llm_server_status():
  """Check LLM server and log URL + model name. Non-fatal if unreachable."""
  import util.config as config
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
  from absl import logging as absl_logging
  import logging as py_logging
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
