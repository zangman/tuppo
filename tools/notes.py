"""Save notes to a configurable file on disk."""

import os
from datetime import datetime

import tzlocal
from absl import logging

import util.config as config

_DEFAULT_PATH = os.path.expanduser("~/Documents/notes.md")


def _get_notes_path() -> str:
  """Return the notes file path from config, or the default."""
  cfg = config.load_config()
  raw = cfg.get("notes", {}).get("path", _DEFAULT_PATH)
  return os.path.expanduser(raw)


def save_note(text: str) -> str:
  """Append a timestamped note to the notes file.

  Raises
  ------
  PermissionError
      If the directory or file is not writable.
  FileNotFoundError
      If the resolved path is invalid.
  OSError
      For other I/O errors (disk full, read-only filesystem, etc.).
  """
  notes_path = _get_notes_path()
  parent_dir = os.path.dirname(notes_path)

  try:
    os.makedirs(parent_dir, exist_ok=True)
  except (PermissionError, OSError) as e:
    logging.error("Failed to create notes directory '%s': %s", parent_dir, e)
    raise

  local_tz = tzlocal.get_localzone()
  now = datetime.now(local_tz)
  timestamp = now.strftime("%Y-%m-%d %H:%M:%S")
  line = f"{timestamp} | {text}\n"

  try:
    with open(notes_path, "a", encoding="utf-8") as f:
      f.write(line)
  except (PermissionError, FileNotFoundError, OSError) as e:
    logging.error("Failed to write note to '%s': %s", notes_path, e)
    raise

  return f"Note saved: {timestamp}"
