# 🛡️ Security Hardening Plan: Role-Based Access Control (RBAC) for AI Tools

## 1. Executive Summary & Threat Model

The current implementation of the Telegram/WhatsApp bot ecosystem shares a single, global list of tools (`tools` in `core_brain.py`) across all sessions. 

### The Vulnerability: Insecure Tool Exposure & Over-Privilege
Because the LLM manages both the owner's Telegram channel (`tg_admin`) and external WhatsApp contacts (`wa_contact`) using the same tool list, a non-admin WhatsApp user can easily bypass conversational boundaries (via prompt injection or direct requests) to:
1.  **Exfiltrate Data**: Ask for full transcripts of other WhatsApp groups/chats (`get_whatsapp_transcript`).
2.  **Snoop Calendars**: Retrieve detailed schedule events, including sensitive descriptions, location data, and attendee lists (`list_calendar_events`).
3.  **Vandalize Schedule**: Create, delete, or modify Google Calendar events without the owner's knowledge or consent (`create_calendar_event`, `delete_calendar_event`, `update_calendar_event`).

### The Goal
To enforce a zero-trust, code-level security model where the LLM's capabilities are strictly constrained by the *identity* of the user it is talking to, rendering prompt injection attacks completely powerless.

---

## 2. Layer 1: Code-Level Tool Isolation

Instead of a single, global list of tools in `core_brain.py`, we will implement **Scope-Based Tool Registries**.

```
              [Incoming Message]
                      │
             (Check Session ID)
                      │
         ┌────────────┴────────────┐
         ▼                         ▼
   Starts with "tg_"        Starts with "wa_"
   (Owner on Telegram)    (Allowlisted Contact)
         │                         │
  ┌──────┴──────┐           ┌──────┴──────┐
  ▼             ▼           ▼             ▼
[Admin Registry]         [Public Registry]
- Calc                   - Calc
- SearXNG Search         - SearXNG Search
- Fetch Page             - Fetch Page
- Get WA Transcript      - Check Availability (Masked)
- Full Calendar CRUD     - Propose Event (Approval Gated)
- Update Profile
```

### Technical Implementation Concept:
1.  Split `tools` in `core_brain.py` into:
    *   `ADMIN_TOOLS`: All existing administrative and reading tools.
    *   `PUBLIC_TOOLS`: Restricted, safe tools.
2.  Modify `get_llm_response` to dynamically assign the `tools` payload based on the incoming `session_id`:
    ```python
    # Conceptual implementation inside get_llm_response:
    if session_id.startswith("tg_"):
        active_tools = ADMIN_TOOLS
    elif session_id.startswith("wa_"):
        active_tools = PUBLIC_TOOLS
    else:
        active_tools = [] # Absolute lock out for un-scoped sessions
    ```
3.  Modify `execute_tool` to throw an immediate error if a session attempts to call a tool outside its allowed registry.

---

## 3. Layer 2: Masked Data Retrieval (The "Anonymizer" Tool)

Allowlisted contacts frequently ask about availability (e.g., *"Are you free tomorrow afternoon?"*). However, they must never see private event descriptions (e.g., *"Therapy Appointment"* or *"Interview with competitor"*).

We will create a specialized, restricted calendar tool: **`check_owner_availability`**.

### Behavior:
*   The tool queries the primary calendar using the Google Calendar API (exactly like `list_calendar_events`).
*   Before returning results to the LLM, a **sanitization step** strips all metadata:
    *   `summary` (Title) is changed to `"BUSY"`.
    *   `description` is deleted entirely.
    *   `attendees` and `hangoutLink` are deleted.
*   **Input**: Date or time range (e.g., `2026-05-29`).
*   **Output to LLM**:
    ```json
    [
      {"start": "2026-05-29T10:00:00Z", "end": "2026-05-29T11:00:00Z", "status": "BUSY"},
      {"start": "2026-05-29T14:30:00Z", "end": "2026-05-29T15:30:00Z", "status": "BUSY"}
    ]
    ```
The LLM can confidently state: *"[Owner] is busy from 10 to 11 AM and 2:30 to 3:30 PM, but he is completely free outside of those times!"* without ever knowing *what* you are doing.

---

## 4. Layer 3: Human-In-The-Loop Writing (Telegram Approval Gates)

External contacts should be allowed to *request* meetings, but not directly write them to your calendar.

We will establish a **Delegated Write Protocol**:

1.  **The Trigger**: A WhatsApp contact says, *"Let's grab coffee tomorrow at 3 PM."*
2.  **The Draft**: The WhatsApp LLM recognizes this request and calls a specialized, safe tool: **`propose_calendar_event`**.
3.  **The Telegram Request**: 
    *   `propose_calendar_event` generates a unique proposal ID.
    *   It sends an interactive message directly to the owner on **Telegram** using the Telegram Bot API:
        ```text
        🔔 EVENT PROPOSAL RECEIVED
        From: [Owner] Sg (WhatsApp)
        Event: Coffee tomorrow at 3 PM
        Time: 2026-05-29, 15:00 - 16:00
        
        [Approve ✅]   [Reject ❌]
        ```
4.  **The Action**:
    *   If you click **[Approve ✅]**: Telegram bot intercepts the callback query and triggers the *actual* Google Calendar API write (`create_calendar_event`). It then writes back to the SQLite DB to notify the WhatsApp session.
    *   If you click **[Reject ❌]**: The proposal is discarded.
5.  **The Feedback**: The WhatsApp LLM is notified of the decision and politely conveys it back to the contact.

---

## 5. Implementation Roadmap

1.  **Phase 1: Code-Level Registry Separation**
    *   Refactor `core_brain.py` to support `ADMIN_TOOLS` and `PUBLIC_TOOLS`.
    *   Assert strict boundaries in `execute_tool`.
2.  **Phase 2: Build Safe Context Tools**
    *   Implement `check_owner_availability` in `tools/google_calendar.py` and assign it to `PUBLIC_TOOLS`.
3.  **Phase 3: Secure Dynamic Profile Reading**
    *   Ensure the profile read for external users only surfaces the specific status fields (like `availability` and `current_location` if explicitly filled) but restricts general sensitive notes.
4.  **Phase 4: Build the Interactive Telegram Gate**
    *   Implement a callback query handler in `bot.py` to process inline keyboard clicks (`[Approve]`/`[Reject]`).
    *   Hook up the draft execution pipeline.
