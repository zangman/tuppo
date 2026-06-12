import asyncio
import os
import sqlite3
import json
from absl import logging
import requests
import datetime
import pytz
import core_brain
from croniter import croniter

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(ROOT_DIR, 'whatsapp.db')
WHATSAPP_API_URL = 'http://localhost:3000/send-message'

async def run_scheduler_cycle(bot, owner_id):
    """
    Checks for pending tasks in the database and executes them.
    """
    # Use UTC for consistent DB comparison
    now_utc = datetime.datetime.now(pytz.utc)
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Find all pending tasks that are due
    # Cron tasks with no execution_time yet are always evaluated (next run time is calculated after first execution)
    cursor.execute(
        "SELECT task_id, owner_id, execution_time, action_type, action_params, cron_expression, status FROM scheduled_tasks WHERE status = 'pending' AND (execution_time <= ? OR (execution_time IS NULL OR execution_time = '') AND cron_expression IS NOT NULL)",
        (now_utc.isoformat(),)
    )
    tasks = cursor.fetchall()
    logging.info(f"--- Scheduler Tick: Found {len(tasks)} due tasks (Current UTC: {now_utc.isoformat()}) ---")
    
    for task in tasks:
        task_id, o_id, exec_time, action, params_json, cron, status = task
        params = json.loads(params_json)
        
        logging.info(f"EXECUTING TASK: {task_id} action={action} params={json.dumps(params, default=str)[:300]}")
        
        try:
            # Execute action
            if action == 'send_summary':
                import tools.whatsapp_summary as whatsapp_summary
                summary = whatsapp_summary.get_chat_history(
                    params.get('group'),
                    params.get('timeframe_hours', 24)
                )
                await bot.send_message(chat_id=owner_id, text=f"📅 Scheduled Summary:\n\n{summary}")
                
            elif action == 'send_whatsapp_message':
                # Handle multiple recipients or single chat_id
                recipients = params.get('recipients', [])
                if not recipients and 'chat_id' in params:
                    recipients = [params['chat_id']]

                text = params.get('message_text', '')
                # Prefix with robot emoji so recipients know it's the bot
                text = f"🤖 {text}"
                sent_ok = 0
                sent_fail = 0
                for rid in recipients:
                    resp = requests.post(WHATSAPP_API_URL, json={
                        "chatId": rid,
                        "text": text
                    })
                    if resp.status_code == 200:
                        sent_ok += 1
                    else:
                        sent_fail += 1
                        logging.error(f"  Failed to send to {rid}: {resp.status_code} {resp.text}")

                status_msg = f"✅ Sent to {sent_ok} recipient(s)."
                if sent_fail > 0:
                    status_msg += f" ❌ Failed: {sent_fail}."
                await bot.send_message(chat_id=owner_id, text=f"📤 Scheduled WhatsApp message: {status_msg}")
                
            elif action == 'send_telegram_reminder':
                text = params.get('message_text', 'Scheduled reminder!')
                await bot.send_message(chat_id=owner_id, text=f"🔔 REMINDER: {text}")
                
            elif action == 'llm_task':
                prompt = params.get('prompt', 'Perform the scheduled task')
                logging.info(f"EXECUTING LLM TASK: prompt={prompt}")
                # Use the admin session format 'tg_<id>' to ensure the LLM has tool access
                session_id = f"tg_{owner_id}" if not str(owner_id).startswith("tg_") else owner_id
                response, _, _ = await core_brain.get_llm_response(session_id, prompt)
                await bot.send_message(chat_id=owner_id, text=f"🤖 Scheduled Task Result:\n\n{response}")

            # Handle Recurrence
            if cron:
                # Calculate next run time using croniter
                # We use UTC for calculation to keep DB offsets consistent
                iter = croniter(cron, now_utc)
                next_run = iter.get_next(datetime.datetime)
                
                cursor.execute(
                    "UPDATE scheduled_tasks SET execution_time = ? WHERE task_id = ?",
                    (next_run.isoformat(), task_id)
                )
            else:
                # Mark one-time task as completed
                cursor.execute("UPDATE scheduled_tasks SET status = 'completed' WHERE task_id = ?", (task_id,))
            
            conn.commit()
        except Exception as e:
            logging.error(f"Error executing task {task_id}: {e}")
            # Mark as failed to avoid infinite retry loops on broken params
            cursor.execute("UPDATE scheduled_tasks SET status = 'failed' WHERE task_id = ?", (task_id,))
            conn.commit()

    conn.close()

async def scheduler_loop(bot, owner_id):
    """
    Background loop that runs the scheduler cycle every 30 seconds.
    """
    logging.info(f"Scheduler background loop started for owner {owner_id}.")
    while True:
        try:
            await run_scheduler_cycle(bot, owner_id)
        except Exception as e:
            logging.error(f"Scheduler loop error: {e}")
        await asyncio.sleep(30)
