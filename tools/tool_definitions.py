"""Tool schema definitions for RBAC-based access control.

Three tiers of tool access, determined by session ID prefix:

  PUBLIC_TOOLS    — available to all sessions (3 tools: calc, searxng_search, fetch_page)
  WHATSAPP_TOOLS  — PUBLIC_TOOLS + calendar availability & proposal (5 tools total)
  ADMIN_TOOLS     — PUBLIC_TOOLS + full admin suite (20 tools total)

Session routing:
  - session_id starts with "tg_" → ADMIN_TOOLS
  - session_id starts with "wa_" → WHATSAPP_TOOLS
  - all others                  → PUBLIC_TOOLS
"""

# Public tools available to all sessions
PUBLIC_TOOLS = [
  {
    "type": "function",
    "function": {
      "name": "calc",
      "description": "Perform a mathematical operation",
      "parameters": {
        "type": "object",
        "properties": {
          "operand1": {
            "type": "number"
          },
          "operand2": {
            "type": "number"
          },
          "operator": {
            "type": "string",
            "enum": ["add", "subtract", "multiply", "divide", "exponent"]
          },
        },
        "required": ["operand1", "operand2", "operator"],
      }
    }
  },
  {
    "type": "function",
    "function": {
      "name":
        "searxng_search",
      "description":
        "Search the web using a local SearXNG search engine. Highly reliable for generic search queries, news, and definitions.",
      "parameters": {
        "type": "object",
        "properties": {
          "query": {
            "type": "string",
            "description": "The search query"
          },
          "num_results": {
            "type": "integer",
            "description": "Number of results to return (1-10)",
            "default": 5
          }
        },
        "required": ["query"],
      }
    }
  },
  {
    "type": "function",
    "function": {
      "name":
        "fetch_page",
      "description":
        "Retrieve the full text/markdown content of a webpage. Use this when you find a URL via web_search and need to read its detailed content to answer the user's question.",
      "parameters": {
        "type": "object",
        "properties": {
          "url": {
            "type": "string",
            "description": "The URL of the webpage to fetch"
          }
        },
        "required": ["url"],
      }
    }
  },
]

# WhatsApp-specific tools (public tools + calendar availability/proposal)
_WHATSAPP_ONLY_TOOLS = [
  {
    "type": "function",
    "function": {
      "name":
        "propose_calendar_event",
      "description":
        "Propose a new event to the owner for approval. Use this when a contact wants to schedule something. The event is only created if the owner approves it on Telegram.",
      "parameters": {
        "type": "object",
        "properties": {
          "summary": {
            "type": "string",
            "description": "Title of the event"
          },
          "start_iso": {
            "type": "string",
            "description": "Start ISO format"
          },
          "end_iso": {
            "type": "string",
            "description": "End ISO format"
          },
          "description": {
            "type": "string",
            "description": "Event description"
          },
          "requester_id": {
            "type": "string",
            "description": "The WhatsApp ID of the person requesting the event"
          }
        },
        "required": ["summary", "start_iso", "end_iso"]
      }
    }
  },
  {
    "type": "function",
    "function": {
      "name":
        "check_owner_availability",
      "description":
        "Check the owner's primary calendar for busy/free slots. Use this to answer queries about when the owner is available.",
      "parameters": {
        "type": "object",
        "properties": {
          "time_min": {
            "type":
              "string",
            "description":
              "Start time in ISO format (e.g. 2026-05-28T00:00:00+08:00). Always use the owner's local timezone offset (+08:00 for SGT) rather than UTC (Z)."
          },
          "time_max": {
            "type":
              "string",
            "description":
              "End time in ISO format (e.g. 2026-05-28T23:59:59+08:00). Always use the owner's local timezone offset (+08:00 for SGT) rather than UTC (Z)."
          }
        }
      }
    }
  },
]

WHATSAPP_TOOLS = PUBLIC_TOOLS + _WHATSAPP_ONLY_TOOLS

ADMIN_TOOLS = PUBLIC_TOOLS + [
  {
    "type": "function",
    "function": {
      "name":
        "find_whatsapp_chat",
      "description":
        "Search WhatsApp contacts/groups by name. Returns matching chat names and their exact chatIds. Use this to resolve a person's or group's chatId before scheduling or sending messages.",
      "parameters": {
        "type": "object",
        "properties": {
          "name": {
            "type": "string",
            "description": "The name or partial name of the contact or group to search for"
          }
        },
        "required": ["name"]
      }
    }
  },
  {
    "type": "function",
    "function": {
      "name":
        "propose_whatsapp_message",
      "description":
        "Create a WhatsApp message proposal for the owner to approve via Telegram inline buttons. Always use this instead of direct sending. After calling this tool, output ONLY the returned [Proposal: <id>] tag with no additional text — the system will convert it into inline buttons.",
      "parameters": {
        "type": "object",
        "properties": {
          "chat_id": {
            "type": "string",
            "description": "The exact WhatsApp chatId (e.g., 1234567890@c.us or 1234567890@g.us)"
          },
          "recipient_name": {
            "type": "string",
            "description": "Display name of the recipient for confirmation"
          },
          "message_text": {
            "type": "string",
            "description": "The message content to send"
          }
        },
        "required": ["chat_id", "recipient_name", "message_text"]
      }
    }
  },
  {
    "type": "function",
    "function": {
      "name":
        "get_whatsapp_new_messages",
      "description":
        "Retrieve only NEW WhatsApp messages from a group or private chat since the last time this tool was used. Use this by default for any 'summary' or 'update' requests. If no new messages are returned, inform the user that there are no new messages; do NOT fallback to get_whatsapp_history unless the user explicitly requests a historical look-back or a specific time range. If used for the first time on a chat, it returns the last 1000 messages and marks them as read.",
      "parameters": {
        "type": "object",
        "properties": {
          "chat_name_query": {
            "type": "string",
            "description": "The name or partial name of the WhatsApp group or chat"
          }
        },
        "required": ["chat_name_query"]
      }
    }
  },
  {
    "type": "function",
    "function": {
      "name":
        "get_whatsapp_history",
      "description":
        "Use ONLY for specific historical lookups, searching for keywords, or when the user explicitly asks for a summary of a specific timeframe (e.g., 'summarize the last 24 hours'). Do not use this for general 'summary' requests. Does NOT affect read status — can re-read old messages. Use this for historical lookups like 'what address was mentioned 2 days ago' or 'find messages about X'.",
      "parameters": {
        "type": "object",
        "properties": {
          "chat_name_query": {
            "type": "string",
            "description": "The name or partial name of the WhatsApp group or chat"
          },
          "timeframe_hours": {
            "type": "integer",
            "description": "How many hours of history to look back",
            "default": 24
          },
          "search_text": {
            "type": "string",
            "description": "Optional keyword or phrase to filter messages by content"
          }
        },
        "required": ["chat_name_query"]
      }
    }
  },
  {
    "type": "function",
    "function": {
      "name":
        "schedule_telegram_reminder",
      "description":
        "Schedule a Telegram reminder for the owner at a future time or on a recurring schedule. For recurring tasks, you MUST provide BOTH execution_time (for the first run) AND cron_expression (for subsequent runs). A task with only execution_time will fire once and be marked completed.",
      "parameters": {
        "type": "object",
        "properties": {
          "execution_time": {
            "type":
              "string",
            "description":
              "ISO format timestamp for the next execution. REQUIRED for one-time tasks. For recurring tasks, must be provided alongside cron_expression."
          },
          "message_text": {
            "type": "string",
            "description": "The reminder text to send."
          },
          "cron_expression": {
            "type":
              "string",
            "description":
              "REQUIRED for recurring tasks. Standard cron syntax (e.g., '0 6,18 * * *' for 6AM and 6PM daily). Omit only for one-time tasks."
          }
        },
        "required": ["message_text"]
      }
    }
  },
  {
    "type": "function",
    "function": {
      "name":
        "schedule_whatsapp_message",
      "description":
        "Schedule a WhatsApp message for future or recurring delivery. MANDATORY: Resolve all names/groups to exact chatIds using find_whatsapp_chat first. Only pass explicit WhatsApp IDs (ending in @c.us or @g.us). For recurring tasks, you MUST provide BOTH execution_time (for the first run) AND cron_expression (for subsequent runs). A task with only execution_time will fire once and be marked completed.",
      "parameters": {
        "type": "object",
        "properties": {
          "execution_time": {
            "type":
              "string",
            "description":
              "ISO format timestamp for the next execution. REQUIRED for one-time tasks. For recurring tasks, must be provided alongside cron_expression."
          },
          "recipients": {
            "type": "array",
            "items": {
              "type": "string"
            },
            "description": "List of WhatsApp chatIds to send to (e.g., ['1234567890@c.us'])."
          },
          "message_text": {
            "type": "string",
            "description": "The message content to send."
          },
          "cron_expression": {
            "type":
              "string",
            "description":
              "REQUIRED for recurring tasks. Standard cron syntax (e.g., '0 6,18 * * *' for 6AM and 6PM daily). Omit only for one-time tasks."
          }
        },
        "required": ["recipients", "message_text"]
      }
    }
  },
  {
    "type": "function",
    "function": {
      "name":
        "schedule_whatsapp_summary",
      "description":
        "Schedule a WhatsApp group summary. Summarizes ONLY new messages since the last report. For recurring reports, set is_recurring to true.",
      "parameters": {
        "type": "object",
        "properties": {
          "group": {
            "type": "string",
            "description": "WhatsApp group name."
          },
          "is_recurring": {
            "type": "boolean",
            "description": "Set to true for repeated summaries (daily/weekly)."
          },
          "execution_time": {
            "type": "string",
            "description": "ISO timestamp (YYYY-MM-DDTHH:MM:SS) for the first/next run."
          },
          "cron_expression": {
            "type": "string",
            "description": "Cron syntax for recurring tasks (e.g., '0 9 * * *' for 9AM daily)."
          }
        },
        "required": ["group", "execution_time", "is_recurring"]
      }
    }
  },
  {
    "type": "function",
    "function": {
      "name":
        "schedule_llm_task",
      "description":
        "Schedule a dynamic LLM task for future or recurring execution. The prompt is evaluated fresh at the scheduled time (e.g., 'get latest news'). For recurring tasks, you MUST provide BOTH execution_time (for the first run) AND cron_expression (for subsequent runs). A task with only execution_time will fire once and be marked completed.",
      "parameters": {
        "type": "object",
        "properties": {
          "execution_time": {
            "type":
              "string",
            "description":
              "ISO format timestamp for the next execution. REQUIRED for one-time tasks. For recurring tasks, must be provided alongside cron_expression."
          },
          "prompt": {
            "type": "string",
            "description": "The task prompt for the LLM to execute at the scheduled time."
          },
          "cron_expression": {
            "type":
              "string",
            "description":
              "REQUIRED for recurring tasks. Standard cron syntax (e.g., '0 6,18 * * *' for 6AM and 6PM daily). Omit only for one-time tasks."
          }
        },
        "required": ["prompt"]
      }
    }
  },
  {
    "type": "function",
    "function": {
      "name": "list_scheduled_tasks",
      "description": "List all currently pending scheduled tasks.",
      "parameters": {
        "type": "object",
        "properties": {}
      }
    }
  },
  {
    "type": "function",
    "function": {
      "name": "cancel_scheduled_task",
      "description": "Cancel a scheduled task using its task_id.",
      "parameters": {
        "type": "object",
        "properties": {
          "task_id": {
            "type": "string",
            "description": "The unique ID of the task to cancel."
          }
        },
        "required": ["task_id"]
      }
    }
  },
  {
    "type": "function",
    "function": {
      "name": "list_user_calendars",
      "description": "List all Google Calendars the user has access to and their IDs.",
      "parameters": {
        "type": "object",
        "properties": {}
      }
    }
  },
  {
    "type": "function",
    "function": {
      "name": "list_calendar_events",
      "description": "List events from all calendars (primary + home) combined with full details. Admin only.",
      "parameters": {
        "type": "object",
        "properties": {
          "time_min": {
            "type":
              "string",
            "description":
              "ISO format start time with timezone offset (e.g. 2026-06-06T00:00:00+08:00 for SGT). Never use Z (UTC) — always use the owner's local timezone offset."
          },
          "time_max": {
            "type":
              "string",
            "description":
              "ISO format end time with timezone offset (e.g. 2026-06-07T23:59:59+08:00 for SGT). Never use Z (UTC) — always use the owner's local timezone offset."
          }
        }
      }
    }
  },
  {
    "type": "function",
    "function": {
      "name": "create_calendar_event",
      "description": "Create a new event in a specific Google Calendar. Admin only.",
      "parameters": {
        "type": "object",
        "properties": {
          "calendar_id": {
            "type": "string",
            "enum": ["primary", "home"],
            "description": "Which calendar: 'primary' (personal) or 'home' (family/home). Defaults to 'primary'."
          },
          "summary": {
            "type": "string",
            "description": "Title"
          },
          "start_iso": {
            "type": "string",
            "description": "Start ISO"
          },
          "end_iso": {
            "type": "string",
            "description": "End ISO"
          },
          "description": {
            "type": "string",
            "description": "Description"
          }
        },
        "required": ["summary", "start_iso", "end_iso"]
      }
    }
  },
  {
    "type": "function",
    "function": {
      "name": "delete_calendar_event",
      "description": "Delete an event from a specific Google Calendar. Admin only.",
      "parameters": {
        "type": "object",
        "properties": {
          "calendar_id": {
            "type": "string",
            "enum": ["primary", "home"],
            "description": "Which calendar: 'primary' (personal) or 'home' (family/home). Defaults to 'primary'."
          },
          "event_id": {
            "type": "string",
            "description": "Event ID"
          }
        },
        "required": ["event_id"]
      }
    }
  },
  {
    "type": "function",
    "function": {
      "name": "update_calendar_event",
      "description": "Update an existing event on a specific Google Calendar. Admin only.",
      "parameters": {
        "type": "object",
        "properties": {
          "calendar_id": {
            "type": "string",
            "enum": ["primary", "home"],
            "description": "Which calendar: 'primary' (personal) or 'home' (family/home). Defaults to 'primary'."
          },
          "event_id": {
            "type": "string",
            "description": "Event ID"
          },
          "summary": {
            "type": "string",
            "description": "New title"
          },
          "start_iso": {
            "type": "string",
            "description": "New start ISO"
          },
          "end_iso": {
            "type": "string",
            "description": "New end ISO"
          },
          "description": {
            "type": "string",
            "description": "New description"
          }
        },
        "required": ["event_id"]
      }
    }
  },
  {
    "type": "function",
    "function": {
      "name": "get_profile",
      "description": "Retrieve the current owner's profile status and personal details. Admin only.",
      "parameters": {
        "type": "object",
        "properties": {}
      }
    }
  },
  {
    "type": "function",
    "function": {
      "name": "update_owner_status",
      "description": "Update a specific field in the owner's profile status. Admin only.",
      "parameters": {
        "type": "object",
        "properties": {
          "key": {
            "type": "string",
            "description": "Field to update"
          },
          "value": {
            "type": "string",
            "description": "New value"
          }
        },
        "required": ["key", "value"]
      }
    }
  },
  {
    "type": "function",
    "function": {
      "name":
        "count_pending_messages",
      "description":
        "Return only the count of pending (unread) messages for the owner, without retrieving the actual message content. Useful for scheduled checks. Admin only.",
      "parameters": {
        "type": "object",
        "properties": {}
      }
    }
  },
  {
    "type": "function",
    "function": {
      "name":
        "get_pending_messages",
      "description":
        "Retrieve messages that people have asked the WhatsApp bot to pass along to the owner. Shows sender, context, message text, and time. Admin only.",
      "parameters": {
        "type": "object",
        "properties": {}
      }
    }
  },
  {
    "type": "function",
    "function": {
      "name": "clear_messages",
      "description": "Mark messages as read or clear all pending messages. Admin only.",
      "parameters": {
        "type": "object",
        "properties": {
          "mode": {
            "type": "string",
            "enum": ["all", "ids"],
            "description": "'all' to clear everything, 'ids' to clear specific messages"
          },
          "ids": {
            "type": "array",
            "items": {
              "type": "integer"
            },
            "description": "Message IDs to clear (only when mode='ids')"
          }
        },
        "required": ["mode"]
      }
    }
  },
  {
    "type": "function",
    "function": {
      "name":
        "check_email_inbox",
      "description":
        "List unread emails in the owner's inbox with sender, subject, preview, and local-time timestamp. Returns Gmail message IDs for follow-up with read_email. Admin only.",
      "parameters": {
        "type": "object",
        "properties": {
          "max_results": {
            "type": "integer",
            "description": "Max emails to return (default 10, max 50)",
            "default": 10
          },
          "query": {
            "type": "string",
            "description": "Gmail search query (e.g. 'from:boss@company.com', 'has:attachment')"
          }
        }
      }
    }
  },
  {
    "type": "function",
    "function": {
      "name":
        "read_email",
      "description":
        "Read the full plain-text content of a specific Gmail message by its message ID. HTML is stripped automatically. Admin only.",
      "parameters": {
        "type": "object",
        "properties": {
          "message_id": {
            "type": "string",
            "description": "The Gmail message ID (from check_email_inbox results)"
          }
        },
        "required": ["message_id"]
      }
    }
  },
  {
    "type": "function",
    "function": {
      "name":
        "mark_emails_read",
      "description":
        "Mark Gmail messages as read. Takes a list of message IDs from check_email_inbox results. Call this after showing emails to the owner so they don't appear again.",
      "parameters": {
        "type": "object",
        "properties": {
          "message_ids": {
            "type": "array",
            "items": {
              "type": "string"
            },
            "description": "Gmail message IDs to mark as read"
          }
        },
        "required": ["message_ids"]
      }
    }
  },
]
