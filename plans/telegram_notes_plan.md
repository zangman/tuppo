# Plan: Telegram `/note` Command

## Objective

Allow the owner to quickly dump thoughts, reminders, or random notes via Telegram using the `/note` command. Notes are saved directly to disk — no LLM involvement. Reading/searching notes is deferred to a future phase.

## How It Works

### The Command

The owner sends:

```
/note Buy groceries on the way home
```

The bot replies:

```
✅ Note saved.
```

If `/note` is sent with no arguments, the bot replies:

```
Usage: /note <your note>
```

### Storage

Notes are appended to a plain-text file whose path is configurable via `config.yaml`:

```yaml
notes:
  path: ~/Documents/notes.md
```

If the `notes.path` key is absent, the default is `~/Documents/notes.md`.

Each note is one line in the format:

```
YYYY-MM-DD HH:MM:SS | <note text>
```

Example file contents:

```
2026-06-20 14:32:00 | Buy groceries on the way home
2026-06-20 15:10:00 | work: Meeting with Alex at 3pm
2026-06-21 09:00:00 | Idea: build a note-taking bot
```

The file and its parent directory are created automatically on first use.

### Design Decisions

1. **Single-line notes only** — each `/note` invocation is one entry. No multi-line or continuation.
2. **No categories or tags** — flat list. The user can prefix notes with descriptive tags (e.g., `work:...`, `home:...`) if desired.
3. **No LLM involvement** — `/note` is a direct command handler. The text goes straight to disk.
4. **No reading/searching yet** — deferred. Future work will add a `read_notes` tool for the LLM and a `/notes` command for direct retrieval.
5. **Plain text, no encryption** — notes are stored as-is on disk.
6. **Configurable save path** — the notes file path is read from `config.yaml` under `notes.path`, defaulting to `~/Documents/notes.md`.
7. **Error handling** — `save_note` catches specific exceptions (`FileNotFoundError`, `PermissionError`, `OSError`), logs them via `absl.logging`, and re-raises them. The caller (`bot.py` handler) catches known exceptions and replies with a user-friendly message. A final `except Exception` at the handler level catches any unexpected runtime errors, logs them, and notifies the user with a generic error message. No errors die silently.

## Changes Required

### 1. New File: `tools/notes.py`

A new module with a single public function:

```python
def save_note(text: str) -> str
```

**Responsibilities:**

- Load the notes file path from `config.yaml` via `util.config.load_config()` under `notes.path`. Default to `~/Documents/notes.md` if the key is absent.
- Resolve `~` via `os.path.expanduser`.
- Ensure the parent directory exists (`os.makedirs` with `exist_ok=True`).
- Append one line: `<timestamp> | <text>\n`
- Use local timezone for the timestamp.
- Return a confirmation string (e.g., `"Note saved: 2026-06-20 14:32"`).

**Error handling:**

The function wraps its I/O logic in a `try/except` block that catches specific exceptions only (no bare `Exception`):

| Exception | When | Action |
|-----------|------|--------|
| `PermissionError` | Can't create directory or write to file | Log via `absl.logging.error`, re-raise |
| `FileNotFoundError` | Parent path is invalid (e.g., non-existent intermediate dir that can't be created) | Log via `absl.logging.error`, re-raise |
| `OSError` | Other I/O errors (disk full, read-only filesystem, etc.) | Log via `absl.logging.error`, re-raise |

The log message includes the exception type and the underlying error message so the root cause is visible in `tuppo.log`.

**Any exception not caught by these handlers** (e.g., `KeyError` from config corruption, `TypeError` from bad data) propagates uncaught from `save_note`. It is caught by the bot handler's final `except Exception` clause, which logs it and notifies the user. This ensures no error dies silently.

**Details:**

- Use `datetime.now()` for the timestamp (or reuse `util.get_time` if timezone-aware formatting is preferred).
- Open file in append mode (`'a'`).
- No truncation or length limits — whatever the user types is saved as-is.

### 2. New File: `tools/tests/test_notes.py`

Unit tests for `save_note`. All tests use a temporary directory (via `tempfile.TemporaryDirectory`) as the config path so no real files are touched.

| Test | Description |
|------|-------------|
| `test_creates_file` | File does not exist → `save_note` creates it and writes one line |
| `test_appends_to_existing` | File exists with content → `save_note` appends without overwriting |
| `test_timestamp_format` | Saved line matches `YYYY-MM-DD HH:MM:SS | ...` |
| `test_return_value` | Return string contains "Note saved" and a timestamp |
| `test_special_characters` | Notes with quotes, emojis, pipes (`|`) are saved correctly |
| `test_multiple_saves` | Two consecutive `save_note` calls produce two lines |
| `test_permission_error` | Unwritable path → `PermissionError` is raised (not swallowed) |
| `test_default_path` | Missing `notes.path` in config → defaults to `~/Documents/notes.md` |
| `test_configured_path` | `notes.path` set in config → notes are written to that path |

### 3. Modify: `bot.py`

Add a new command handler that catches errors from `save_note` and replies with a user-friendly message:

```python
import tools.notes as notes

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
        # Catch-all for unexpected runtime errors (config corruption, etc.)
        # Logs the full traceback; user gets a generic message.
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="❌ Something went wrong saving your note. Check the logs.",
        )
```

Register in `main()`:

```python
note_handler = CommandHandler('note', note)
application.add_handler(note_handler)
```

**Error response strategy:**

| Exception | Bot reply |
|-----------|----------|
| `PermissionError` | `"❌ Can't save note — permission denied. Check the notes file path in config.yaml."` |
| `FileNotFoundError` | `"❌ Can't save note — <underlying error message>"` |
| `OSError` | `"❌ Can't save note — <underlying error message>"` |
| `Exception` (catch-all) | `"❌ Something went wrong saving your note. Check the logs."` |

The raw error is also logged by `save_note` itself, so the full diagnostic trail is in `tuppo.log`.

### 4. No Changes to `tool_definitions.py` or `core_brain.py`

This feature is purely a Telegram command handler — no LLM tool calling involved. Those files are untouched.

## Edge Cases

| Case | Handling |
|------|----------|
| `/note` with no text | Reply with usage hint |
| Very long notes | Saved as-is, no truncation |
| Special characters (quotes, pipes, unicode) | Saved as-is |
| Configured path's parent dir doesn't exist | Created automatically via `os.makedirs(exist_ok=True)` |
| Permission error on write | `save_note` logs + re-raises `PermissionError` → bot replies with permission-denied message |
| Disk full / I/O error | `save_note` logs + re-raises `OSError` → bot replies with error detail |
| `notes.path` missing from config | Falls back to `~/Documents/notes.md` |
| Unexpected runtime error (e.g., config corruption, type error) | `save_note` lets it propagate → bot handler's catch-all `except Exception` logs it and notifies the user with a generic error message |
| Rapid successive `/note` calls | Each gets its own line (append is atomic for single writes) |

## Future Work (Deferred)

- **`read_notes` tool** — LLM-facing tool to read and search notes
- **`/notes` command** — Direct Telegram command to view recent notes
- **Categories/tags** — Structured metadata if needed
- **Search** — Filter notes by keyword or date range
- **Encryption** — If privacy concerns arise

## Status

Not started.

*Created: 2026-06-20*
