# Plan: Unified YAML Config

Merge `owner_profile.json` and `autoresponder_config.json` into a single `config.yaml`, and add LLM server configuration.

## Target `config.yaml`

```yaml
owner:
  name: "YourName"
  chat_id: "123456789"
  whatsapp_id: "65XXXXXXXXXX"
  timezone: Asia/Singapore
  home_calendar_id: "..."  # Google Calendar ID
  status:
    current_location: Unknown
    current_focus: Unknown
    availability: Available

llm:
  base_url: http://localhost:8080

whatsapp:
  autoresponder:
    enabled: false
    test_mode: false
    allowed_targets:
      - "1234567890@c.us"
    allowed_groups:
      - "1234567890@g.us"
    response_delay:
      min_seconds: 5
      max_seconds: 15
    fallback_message: "not sure"
    context_window:
      enabled: true
      private_message_count: 10
      group_message_count: 10
    safety_fuse:
      private_max_messages: 3
      private_window_seconds: 60
      group_max_per_sender: 2
      group_window_seconds: 60
```

## Dependency Changes

| File | Change |
|---|---|
| `requirements.txt` | Add `pyyaml` |
| `whatsapp_server/package.json` | Add `js-yaml` |

## File-by-File Migration

| File | Current Source | New Source |
|---|---|---|
| `core_brain.py` | Hardcoded `http://localhost:8080` | `config['llm']['base_url']` → derive `_URL`, `_MODELS_URL`, `_HEADERS` |
| `tools/owner_profile.py` | `owner_profile.json` | `config['owner']` (read + write-back for runtime status updates) |
| `tools/google_calendar.py` | `owner_profile.json` | `config['owner']['chat_id']`, `config['owner']['timezone']`, `config['owner']['home_calendar_id']` |
| `whatsapp_agent.py` | `autoresponder_config.json` + `owner_profile.json` | `config['whatsapp']['autoresponder']` + `config['owner']` |
| `whatsapp_server/index.js` | `autoresponder_config.json` + `owner_profile.json` | `config['whatsapp']['autoresponder']['allowed_groups']` + `config['owner']['whatsapp_id']` |
| `bot.py` (`/wa_*` commands) | `autoresponder_config.json` | `config['whatsapp']['autoresponder']` |
| `scheduler_manager.py` | `owner_profile.json` | `config['owner']['chat_id']`, `config['owner']['timezone']` |

## Notes

- `owner.status.*` fields (location, focus, availability) are updated at runtime by the LLM via `update_owner_status` — those writes go back to the YAML file.
- YAML supports inline comments for documentation.
- Both Python (`pyyaml`) and Node (`js-yaml`) have mature YAML parsers.

## Cleanup

After migration is complete and verified:
- Delete `owner_profile.json`
- Delete `autoresponder_config.json`
