# Plans

Design documents created for major features before implementation.

Each plan outlines the architecture, data flow, tool definitions, and edge cases for a given feature. They were sometimes cross-reviewed by **Gemini 3.5 Flash** for feedback before being built.

Most of these have been implemented, but some may remain as future work.

## Plans

| File | Status |
|------|--------|
| `browser_tool_plan.md` / `browser_tool_critique.md` | Partially implemented / under review |
| `scheduling_automation_plan.md` | ✅ Implemented |
| `security_hardening_plan.md` | Partially implemented |
| `style_mimicry_plan.md` | Partially implemented |
| `unified_yaml_config_plan.md` | ✅ Implemented |
| `whatsapp_autoresponder_plan.md` | ✅ Implemented |
| `whatsapp_context_awareness_plan.md` | ✅ Implemented |
| `whatsapp_group_autoresponder_plan.md` | ✅ Implemented |
| `whatsapp_messaging_plan.md` | ✅ Implemented |
| `whatsapp_take_message_plan.md` | ✅ Implemented |
| `telegram_notes_plan.md` | Planned |

## How to read them

Each plan typically includes:
- **Goal** — what the feature solves
- **Architecture** — components, data flow, DB changes
- **Tool definitions** — JSON schemas for LLM function calling
- **Edge cases & safety** — rate limits, loops, RBAC, error handling
- **Status** — whether it's done, partial, or deferred
