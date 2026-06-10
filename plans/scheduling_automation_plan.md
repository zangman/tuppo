# Plan: Scheduling & Automation Engine (Refined)

This document outlines the implementation of a scheduling system that allows the owner to automate tasks and reminders via the Telegram bot, incorporating robust enterprise-grade scheduling practices.

## 1. Objectives
- Enable the bot to perform actions at a specific future time.
- Support one-time reminders and complex recurring tasks using Cron syntax.
- Support relative time requests (e.g., "remind me in 2 hours").
- Ensure all scheduled tasks persist across bot restarts and handle missed executions (misfires) gracefully.

## 2. Technical Architecture

### A. Storage (`whatsapp.db`)
A new table `scheduled_tasks` will be created to track all planned actions:
- `task_id` (TEXT, PRIMARY KEY): Unique identifier for the task.
- `owner_id` (TEXT): The Telegram ID of the owner.
- `execution_time` (DATETIME): The ISO timestamp for the next execution (or NULL if purely cron-based without a specific start).
- `action_type` (TEXT): `send_summary`, `send_message`, or `telegram_reminder`.
- `action_params` (TEXT/JSON): Arguments for the action (e.g., `{"chat_id": "12345-678@g.us", "text": "Hello"}`).
- `cron_expression` (TEXT): Standard cron syntax for recurring tasks (e.g., `0 6,18 * * *`). NULL for one-time tasks.
- `status` (TEXT): `pending`, `completed`, `cancelled`, `failed`.

### B. Scheduling Engine (Database-as-Queue)
Instead of directly injecting jobs from synchronous LLM tools into an async memory scheduler, we will decouple them using a **Database Polling** worker:
- **The Worker**: A lightweight background asyncio loop in `bot.py` that wakes up every 30 seconds.
- **The Logic**: It queries the `scheduled_tasks` table for any records where `execution_time <= NOW()` and `status = 'pending'`.
- **Execution**:
  1. Reads `action_type` and `action_params`.
  2. Executes the logic (calling WA API, sending Telegram messages, etc.).
  3. If `cron_expression` is present, calculates the *next* execution time and updates the record. If one-time, marks as `completed`.
- **Misfire Handling**: If the bot is offline and misses a task by a wide margin (e.g., > 1 hour), the worker will decide based on the action:
  - *Reminders/Summaries*: Execute immediately upon wake-up.
  - *Messages to others*: Skip and mark as `failed` (to avoid sending someone a weirdly timed delayed message).

### C. LLM Integration (`core_brain.py`)
Three new tools will be added to `ADMIN_TOOLS`:
1. **`schedule_task(execution_time, action, params, cron_expression=None)`**:
   - **Early Resolution Mandate**: The LLM *must* resolve all names/groups to explicit `chatId`s using `find_whatsapp_chat` *before* calling this tool. The `params` will only accept exact IDs.
   - The tool strictly writes the intent to the SQLite DB.
2. **`list_scheduled_tasks()`**:
   - Retrieves and returns a formatted list of all upcoming `pending` tasks.
3. **`cancel_scheduled_task(task_id)`**:
   - Marks the DB record as `cancelled`.

## 3. Use Case Mapping

| User Request | Pre-requisite LLM Action | Tool Call & Engine Execution |
| :--- | :--- | :--- |
| **"WA summary of expat dads at 6AM/6PM"** | Resolves "expat dads" to `chatId: 123-456@g.us` | `schedule_task(..., cron_expression="0 6,18 * * *", params={"chat_id": "123-456@g.us"})`. Worker triggers daily at 6AM/6PM. |
| **"Remind me to call mom at 3PM Sunday"** | None (Internal reminder) | `schedule_task(execution_time="...T15:00:00", action="telegram_reminder", params={"text": "Call mom"})`. |
| **"Send msg to X, Y, Z at 6PM"** | Calls `find_whatsapp_chat` for X, Y, and Z to get their `chatId`s. | `schedule_task(..., params={"recipients": ["X_ID", "Y_ID", "Z_ID"], "text": "..."})`. |
| **"Remind me in 2 hours"** | Calculates `now + 2h` in SGT. | `schedule_task(execution_time=now + 2h, action="telegram_reminder", ...)` |

## 4. Safety & Reliability
- **Early Identity Resolution**: By forcing the LLM to find the exact `chatId` before scheduling, we eliminate the risk of ambiguous contacts or failed searches at execution time.
- **Robust Recurrence (Cron)**: Using standard Cron syntax eliminates LLM hallucinations over custom string identifiers.
- **Decoupled Architecture**: The LLM solely writes to the database, while the background worker solely reads from it. This prevents thread locks, memory leaks, and perfectly handles server reboots natively.
- **Timezone Awareness**: All timestamp and cron calculations will inherently use the `timezone` defined in `owner_profile.json` (e.g., Asia/Singapore).
