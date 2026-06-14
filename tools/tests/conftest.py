import sqlite3
import os
import sys
import types
from datetime import datetime, timedelta
import pytest


def _now_str():
  """Current time as 'YYYY-MM-DD HH:MM:SS'."""
  return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _recent_str(hours_ago=1):
  """A timestamp hours_ago hours ago as 'YYYY-MM-DD HH:MM:SS'."""
  return (datetime.now() - timedelta(hours=hours_ago)).strftime("%Y-%m-%d %H:%M:%S")


def _old_str(days_ago=30):
  """A timestamp days_ago days ago as 'YYYY-MM-DD HH:MM:SS'."""
  return (datetime.now() - timedelta(days=days_ago)).strftime("%Y-%m-%d %H:%M:%S")


@pytest.fixture
def tmp_db_path(tmp_path):
  """Create a temporary SQLite DB with the WhatsApp schema and yield its path."""
  db_path = tmp_path / "whatsapp.db"
  conn = sqlite3.connect(str(db_path))
  cursor = conn.cursor()
  cursor.execute("CREATE TABLE whatsapp_messages ("
                 "id INTEGER PRIMARY KEY AUTOINCREMENT, "
                 "message_id TEXT UNIQUE, "
                 "group_id TEXT, "
                 "group_name TEXT, "
                 "sender TEXT, "
                 "text TEXT, "
                 "timestamp DATETIME DEFAULT CURRENT_TIMESTAMP"
                 ")")
  cursor.execute("CREATE TABLE chat_status ("
                 "chat_id TEXT PRIMARY KEY, "
                 "last_read_timestamp DATETIME"
                 ")")
  conn.commit()
  conn.close()
  return str(db_path)


@pytest.fixture
def populated_db(tmp_db_path):
  """Populate the temp DB with sample chats and messages, then yield the path."""
  conn = sqlite3.connect(tmp_db_path)
  cursor = conn.cursor()

  # Chat 1: "Family Group" with several recent messages
  cursor.executemany(
    "INSERT INTO whatsapp_messages (message_id, group_id, group_name, sender, text, timestamp) "
    "VALUES (?, ?, ?, ?, ?, ?)",
    [
      ("m1", "gid_family", "Family Group", "Mom", "Dinner at 7?", _recent_str(hours_ago=3)),
      ("m2", "gid_family", "Family Group", "Dad", "Sounds good", _recent_str(hours_ago=2.9)),
      ("m3", "gid_family", "Family Group", "Mom", "Great, see you then", _recent_str(hours_ago=2.8)),
    ],
  )

  # Chat 2: "Work Team" with a few recent messages
  cursor.executemany(
    "INSERT INTO whatsapp_messages (message_id, group_id, group_name, sender, text, timestamp) "
    "VALUES (?, ?, ?, ?, ?, ?)",
    [
      ("m4", "gid_work", "Work Team", "Alice", "Meeting at 3pm", _recent_str(hours_ago=1)),
      ("m5", "gid_work", "Work Team", "Bob", "Can't make it", _recent_str(hours_ago=0.8)),
    ],
  )

  # Chat 3: "Old Chat" with very old messages (beyond 7 days)
  cursor.executemany(
    "INSERT INTO whatsapp_messages (message_id, group_id, group_name, sender, text, timestamp) "
    "VALUES (?, ?, ?, ?, ?, ?)",
    [
      ("m6", "gid_old", "Old Chat", "Someone", "Hello from long ago", _old_str(days_ago=30)),
    ],
  )

  conn.commit()
  conn.close()
  return tmp_db_path


@pytest.fixture
def mock_config(monkeypatch):
  """Mock util.config.load_config to return a controlled dict."""
  fake_config = types.ModuleType("util.config")
  fake_config.load_config = lambda: {"owner": {"timezone": "Asia/Singapore"}}
  monkeypatch.setitem(sys.modules, "util.config", fake_config)
  # Also patch the parent so 'import util.config as config' works
  fake_util = types.ModuleType("util")
  fake_util.config = fake_config
  monkeypatch.setitem(sys.modules, "util", fake_util)
  return fake_config
