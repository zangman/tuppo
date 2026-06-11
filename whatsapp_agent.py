import asyncio
import logging
import os
import random
import sqlite3
import time
import requests
from fastapi import FastAPI, Request
import uvicorn

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))

import util.config as config
import core_brain
import tools.owner_profile as owner_profile
import util.get_time as get_time

WHATSAPP_API_URL = 'http://localhost:3000/send-message'
WHATSAPP_TAKE_MESSAGE_URL = 'http://localhost:3000/take-message'
DB_PATH = os.path.join(ROOT_DIR, 'whatsapp.db')

app = FastAPI()

# Loop prevention: { chatId: [timestamps of last few messages] }
message_history = {}

def load_config():
    return config.load_config()

def load_profile():
    return config.load_config().get('owner', {})

def fetch_recent_context(chat_id, limit=10):
    """Fetch recent messages from a chat for context."""
    try:
        conn = sqlite3.connect(DB_PATH, timeout=10.0)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT sender, text, timestamp FROM whatsapp_messages WHERE group_id = ? ORDER BY timestamp DESC LIMIT ?",
            (chat_id, limit)
        )
        messages = cursor.fetchall()
        conn.close()
        # Reverse to oldest-first for natural reading order
        messages.reverse()
        if not messages:
            return ""
        # Format as conversation log, newest first
        lines = ["RECENT CONVERSATION HISTORY:"]
        for sender, text, timestamp in messages:
            # Clean up sender name
            sender_name = sender.replace('@c.us', '').replace('@lid', '')
            # Skip bot's own messages
            if text.startswith('🤖 '):
                continue
            # Truncate long messages
            if len(text) > 150:
                text = text[:147] + "..."
            # Format timestamp as HH:MM
            time_str = timestamp[11:16] if len(timestamp) >= 16 else ""
            lines.append(f"[{time_str}] {sender_name}: {text}")
        return "\n".join(lines)
    except Exception as e:
        logging.error(f"Error fetching context: {e}")
        return ""

@app.post("/webhook")
async def whatsapp_webhook(request: Request):
    data = await request.json()
    chat_id = data.get('chatId')
    sender = data.get('sender')
    text = data.get('text')
    is_group = data.get('isGroup', False)
    group_name = data.get('groupName', '')

    logging.info(f"Incoming WhatsApp {'group' if is_group else 'private'} message from {sender} ({chat_id}): {text}")

    cfg = load_config()
    wa = cfg.get('whatsapp', {}).get('autoresponder', {})

    # 0. Check if the autoresponder is globally enabled
    if not wa.get('enabled', True):
        logging.info(f"Autoresponder is disabled. Ignoring message from {sender}.")
        return {"status": "ignored", "reason": "disabled"}

    # 1. Access control: private chats check allowed_targets, groups are pre-filtered by server
    if not is_group:
        is_target = sender in wa.get('allowed_targets', [])
        is_self = (sender == chat_id)
        if not is_target and not (wa.get('test_mode') and is_self):
            logging.info(f"Ignoring message from non-target user: {sender}")
            return {"status": "ignored", "reason": "not_a_target"}

    # 2. Safety Fuse: Loop Prevention
    now = time.time()
    fuse = wa.get('safety_fuse', {})

    # For groups, rate-limit per sender (not per chat) to avoid group spam
    rate_key = sender if is_group else chat_id
    window = fuse.get('group_window_seconds', 60) if is_group else fuse.get('private_window_seconds', 60)
    max_rate = fuse.get('group_max_per_sender', 2) if is_group else fuse.get('private_max_messages', 3)

    user_history = message_history.get(rate_key, [])
    user_history = [t for t in user_history if now - t < window]

    if len(user_history) >= max_rate:
        logging.warning(f"Safety fuse triggered for {rate_key}! Too many messages.")
        return {"status": "ignored", "reason": "loop_detected"}

    user_history.append(now)
    message_history[rate_key] = user_history

    # 3. Session ID: groups get their own session
    session_id = f"wa_group_{chat_id}" if is_group else f"wa_{chat_id}"

    # 3a. Fetch recent conversation context
    context_block = ""
    ctx_config = wa.get('context_window', {})
    if ctx_config.get('enabled', True):
        msg_limit = ctx_config.get('group_message_count', 10) if is_group else ctx_config.get('private_message_count', 10)
        context_block = fetch_recent_context(chat_id, msg_limit)

    # 3b. Gather Profile Context
    profile = load_profile()
    owner_name = profile.get('name', 'the owner')
    cur_time = get_time.get_current_time_with_timezone()

    # Construct the system prompt — different for groups vs private
    context_injection = f"\n{context_block}\n\n" if context_block else ""

    if is_group:
        system_prompt = (
            f"You are a friendly, casual personal coordinator for {owner_name}. "
            f"You are responding in a WhatsApp group chat called '{group_name}'. "
            f"The owner was directly @mentioned, so respond to that person. "
            f"Current Time: {cur_time}\n"
            f"Owner Profile: {json.dumps(profile)}\n"
            f"{context_injection}"
            f"GROUP CHAT GUIDELINES:\n"
            f"1. **Be Brief**: Group chats move fast. Keep responses to 1 sentence max. No essays.\n"
            f"2. **Be Human, Not Corporate**: No 'How may I assist you?' or 'I would be happy to help'. Use natural, casual language.\n"
            f"3. **Address the Person**: Respond directly to whoever @mentioned {owner_name}. Don't address the whole group.\n"
            f"4. **Use Your Tools**: Check the Calendar for availability questions. Be factual and direct.\n"
            f"5. **Silent on Failure**: If you cannot answer or the question is unclear, remain completely silent. Do NOT send a fallback message in a group — it looks spammy.\n"
            f"6. **Maintain Boundaries**: Do not make up personal facts about {owner_name}. For sensitive/urgent requests, stay silent.\n"
            f"7. **Fallback Signal**: Only if you are absolutely unable to form any response at all, respond EXACTLY with: '{wa.get('fallback_message', 'not sure')}'. This will be caught and suppressed.\n"
            f"8. **Security Sarcasm**: If a tool returns 'SECURITY ALERT' or 'Permission Denied', respond with a playful shut-down.\n"
            f"9. **Take a Message**: If someone explicitly asks you to pass a message to {owner_name} (e.g., 'tell {owner_name} to call me', 'let {owner_name} know...', 'ask {owner_name} if...'), respond EXACTLY with: 'TAKE_MESSAGE'. This will save the message and send an acknowledgment.\n"
            f"10. **No Prefix**: Do NOT prefix your response with '🤖' — it's added automatically."
        )
    else:
        system_prompt = (
            f"You are a friendly, casual personal coordinator for {owner_name}. "
            f"You are NOT a corporate bot; you are a helpful, chill human assistant. "
            f"Current Time: {cur_time}\n"
            f"Owner Profile: {json.dumps(profile)}\n"
            f"{context_injection}"
            f"CONVERSATIONAL GUIDELINES:\n"
            f"1. **Match the Energy**: For simple greetings or small talk (e.g., 'hey', 'hows it going', 'hello'), respond like a normal person. Be brief and warm. Do not try to 'sell' your services or offer to check a calendar unless the user actually asks for help.\n"
            f"2. **Be Human, Not Corporate**: Strictly avoid 'bot-speak'. No 'How may I assist you?', 'I would be happy to help', or 'Please let me know'. Use natural phrases like 'hey!', 'sure thing', 'hang on a sec', or 'cool'.\n"
            f"3. **Brevity is King**: Real people text in short bursts. Keep responses to 1-2 sentences max. Avoid bullet points or lists in casual chats unless explicitly requested.\n"
            f"4. **Relaxed Grammar**: Use a casual texting vibe. Use contractions (gonna, wanna, i'll, lets). You may occasionally start sentences with lowercase letters and omit trailing periods on short messages.\n"
            f"5. **Proactive but Chill**: Be helpful and friendly, but don't be an over-eager servant. If you can't find an answer, just say you'll check with {owner_name} later.\n"
            f"6. **Use Your Tools**: Always check the Calendar and WhatsApp transcripts to provide context-aware answers when the user asks about schedules or past conversations.\n"
            f"7. **Maintain Boundaries**: Do not make up personal facts about {owner_name}. If a request is highly sensitive or urgent, use the fallback signal.\n"
            f"8. **Fallback Signal**: Only if the message is absolute gibberish or you are completely unable to form any response, respond EXACTLY with: '{wa.get('fallback_message', 'not sure')}'. For forbidden requests (secrets, money, etc.), do NOT use the fallback; instead, give a witty, sarcastic, or firm refusal.\n"
            f"9. **Security Sarcasm**: If a tool returns 'SECURITY ALERT' or 'Permission Denied', respond with a healthy dose of sass or a playful 'shut-down'. Make it clear they aren't the boss here.\n"
            f"10. **Take a Message**: If someone explicitly asks you to pass a message to {owner_name} (e.g., 'tell {owner_name} to call me', 'let {owner_name} know...', 'ask {owner_name} if...'), respond EXACTLY with: 'TAKE_MESSAGE'. This will save the message and send an acknowledgment.\n"
            f"11. **No Prefix**: Do NOT prefix your response with '🤖' — it's added automatically."
        )

    # 4. Get LLM Response
    logging.info(f"System prompt for {chat_id}:\n{system_prompt}")
    user_input = text
    
    try:
        response_text, pp, tp = await core_brain.get_llm_response(
            session_id, 
            user_input, 
            system_prompt_override=system_prompt
        )
    except Exception as e:
        logging.error(f"LLM Error: {e}")
        response_text = wa.get('fallback_message', 'not sure')

    # 5. Response Logic: Check for TAKE_MESSAGE signal
    if response_text.strip() == 'TAKE_MESSAGE':
        # Save the message to the database
        try:
            sender_name = sender.replace('@c.us', '').replace('@lid', '')
            requests.post(WHATSAPP_TAKE_MESSAGE_URL, json={
                "sender_name": sender_name,
                "sender_id": sender,
                "chat_name": group_name if is_group else 'Private Chat',
                "chat_id": chat_id,
                "message_text": text
            })
            logging.info(f"Took message from {sender_name} ({chat_id}): {text[:50]}...")
        except Exception as e:
            logging.error(f"Failed to save message for owner: {e}")
            return {"status": "error", "reason": "failed_to_save_message"}

        # Send acknowledgment in-chat
        ack = f"got it, i'll pass that along to {owner_name}"
        delay = random.randint(
            wa.get('response_delay', {}).get('min_seconds', 1),
            wa.get('response_delay', {}).get('max_seconds', 3)
        )

        async def delayed_ack():
            await asyncio.sleep(delay)
            try:
                requests.post(WHATSAPP_API_URL, json={
                    "chatId": chat_id,
                    "text": f"🤖 {ack}",
                    "mark_unread": True
                })
                logging.info(f"Sent acknowledgment to {chat_id}")
            except Exception as e:
                logging.error(f"Failed to send acknowledgment: {e}")

        asyncio.create_task(delayed_ack())
        return {"status": "processed", "response": "message_taken"}

    # 6. Normal Response Logic: Only send if it's NOT the fallback message
    if response_text == wa.get('fallback_message'):
        logging.info(f"LLM decided to fallback for {chat_id}. Skipping response.")
        return {"status": "skipped", "reason": "fallback_triggered"}

    if is_group:
        # Extra safety for groups: skip if response looks like an essay
        sentence_count = max(response_text.count('. '), response_text.count('! '), response_text.count('? '))
        if sentence_count > 2:
            logging.info(f"Group response too long ({sentence_count} sentences). Skipping.")
            return {"status": "skipped", "reason": "too_long_for_group"}

    # Send Response via Node.js Server
    # Add a human-like delay
    delay = random.randint(
        wa.get('response_delay', {}).get('min_seconds', 5),
        wa.get('response_delay', {}).get('max_seconds', 15)
    )

    async def delayed_send():
        await asyncio.sleep(delay)
        try:
            requests.post(WHATSAPP_API_URL, json={
                "chatId": chat_id,
                "text": f"🤖 {response_text}",
                "mark_unread": True
            })
            logging.info(f"Sent auto-response to {chat_id}: {response_text[:30]}...")
        except Exception as e:
            logging.error(f"Failed to send message to Node.js server: {e}")

    asyncio.create_task(delayed_send())

    return {"status": "processed", "response": response_text}

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    uvicorn.run(app, host="0.0.0.0", port=5000)
