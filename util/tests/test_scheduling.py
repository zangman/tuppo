"""Tests for util/scheduling.py."""

import json
import os
import sqlite3
import sys
import types
from unittest.mock import patch, MagicMock

import pytest
import pytz

from util import scheduling as sched

# ── Fixtures ──────────────────────────────────────────────────────────


@pytest.fixture
def sched_db_path(tmp_path):
  """Create a temp SQLite DB with the scheduled_tasks schema."""
  db_path = tmp_path / "sched.db"
  conn = sqlite3.connect(str(db_path))
  cursor = conn.cursor()
  cursor.execute("CREATE TABLE scheduled_tasks ("
                 "task_id TEXT PRIMARY KEY, "
                 "owner_id TEXT, "
                 "execution_time TEXT, "
                 "action_type TEXT, "
                 "action_params TEXT, "
                 "cron_expression TEXT, "
                 "status TEXT"
                 ")")
  conn.commit()
  conn.close()
  return str(db_path)


@pytest.fixture
def mock_config(monkeypatch):
  """Mock util.config.load_config to return a controlled dict."""
  fake_config = types.ModuleType("util.config")
  fake_config.load_config = lambda: {
    "owner": {
      "owner_chat_id": "12345",
      "timezone": "Asia/Singapore",
    }
  }
  monkeypatch.setitem(sys.modules, "util.config", fake_config)
  fake_util = types.ModuleType("util")
  fake_util.config = fake_config
  monkeypatch.setitem(sys.modules, "util", fake_util)
  return fake_config


@pytest.fixture
def mock_core_brain_token(monkeypatch, tmp_path):
  """Mock core_brain.ROOT_DIR and write a token file. Returns the token string."""
  token_file = tmp_path / "token"
  token_file.write_text("test-bot-token-999")
  fake_core_brain = types.ModuleType("core_brain")
  fake_core_brain.ROOT_DIR = str(tmp_path)
  monkeypatch.setitem(sys.modules, "core_brain", fake_core_brain)
  return "test-bot-token-999"


# ── validate_schedule_args ────────────────────────────────────────────


class TestValidateScheduleArgs:

  def test_missing_execution_time(self):
    _, _, err = sched.validate_schedule_args({})
    assert err is not None
    assert "execution_time is required" in err

  def test_recurring_without_cron(self):
    _, _, err = sched.validate_schedule_args({
      "execution_time": "2025-07-01T10:00:00",
      "is_recurring": True,
    })
    assert err is not None
    assert "cron_expression is required" in err

  def test_valid_non_recurring(self):
    et, cron, err = sched.validate_schedule_args({
      "execution_time": "2025-07-01T10:00:00",
    })
    assert err is None
    assert et == "2025-07-01T10:00:00"
    assert cron is None

  def test_valid_recurring(self):
    et, cron, err = sched.validate_schedule_args({
      "execution_time": "2025-07-01T10:00:00",
      "is_recurring": True,
      "cron_expression": "0 10 * * *",
    })
    assert err is None
    assert et == "2025-07-01T10:00:00"
    assert cron == "0 10 * * *"

  def test_extra_keys_ignored(self):
    et, cron, err = sched.validate_schedule_args({
      "execution_time": "2025-07-01T10:00:00",
      "message_text": "hello",
      "recipients": ["alice"],
    })
    assert err is None
    assert et == "2025-07-01T10:00:00"


# ── normalize_execution_time ──────────────────────────────────────────


class TestNormalizeExecutionTime:

  def test_naive_time_converted_to_utc(self):
    result, err = sched.normalize_execution_time("2025-06-15T09:00:00")
    assert err is None
    assert result is not None
    # Naive → SG (+8) → UTC = 01:00 UTC
    dt = pytz.utc.localize(__import__("datetime").datetime(2025, 6, 15, 1, 0, 0))
    assert result == dt.isoformat()

  def test_timezone_aware_passthrough(self):
    result, err = sched.normalize_execution_time("2025-06-15T09:00:00+08:00")
    assert err is None
    assert "01:00" in result  # 09:00+08 → 01:00 UTC

  def test_invalid_format(self):
    _, err = sched.normalize_execution_time("not-a-date")
    assert err is not None
    assert "could not parse" in err


# ── flatten_schedule_params ───────────────────────────────────────────


class TestFlattenScheduleParams:

  def test_strips_both_keys(self):
    result = sched.flatten_schedule_params({
      "execution_time": "2025-07-01T10:00:00",
      "cron_expression": "0 10 * * *",
      "message_text": "hello",
    })
    assert result == {"message_text": "hello"}

  def test_no_extra_keys(self):
    result = sched.flatten_schedule_params({
      "execution_time": "2025-07-01T10:00:00",
      "cron_expression": "0 10 * * *",
    })
    assert result == {}

  def test_extra_keys_preserved(self):
    result = sched.flatten_schedule_params({
      "execution_time": "2025-07-01T10:00:00",
      "recipients": ["alice", "bob"],
      "message_text": "hi",
    })
    assert result == {"recipients": ["alice", "bob"], "message_text": "hi"}


# ── insert_scheduled_task ─────────────────────────────────────────────


class TestInsertScheduledTask:

  def test_inserts_and_reads_back(self, sched_db_path):
    sched.insert_scheduled_task(
      sched_db_path,
      "abc12345",
      "owner1",
      "2025-07-01T10:00:00+00:00",
      "send_telegram_reminder",
      {"message_text": "hello"},
      None,
    )
    conn = sqlite3.connect(sched_db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM scheduled_tasks WHERE task_id = ?", ("abc12345",))
    row = cursor.fetchone()
    conn.close()
    assert row is not None
    assert row[0] == "abc12345"
    assert row[1] == "owner1"
    assert row[5] is None  # cron_expression
    assert row[6] == "pending"

  def test_params_stored_as_json(self, sched_db_path):
    params = {"recipients": ["alice"], "message_text": "hi"}
    sched.insert_scheduled_task(
      sched_db_path,
      "t1",
      "o1",
      "2025-07-01T10:00:00+00:00",
      "send_whatsapp_message",
      params,
      "0 10 * * *",
    )
    conn = sqlite3.connect(sched_db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT action_params, cron_expression FROM scheduled_tasks WHERE task_id = ?", ("t1",))
    params_str, cron = cursor.fetchone()
    conn.close()
    assert json.loads(params_str) == params
    assert cron == "0 10 * * *"


# ── load_scheduling_credentials ───────────────────────────────────────


class TestLoadSchedulingCredentials:

  def test_success(self, mock_config, mock_core_brain_token, monkeypatch):
    cfg = mock_config.load_config()
    creds = sched.load_scheduling_credentials(cfg)
    assert creds["bot_token"] == "test-bot-token-999"
    assert creds["owner_id"] == "12345"
    assert creds["owner_tz"] == pytz.timezone("Asia/Singapore")

  def test_fallback_to_chat_id(self, mock_config, mock_core_brain_token, monkeypatch):
    mock_config.load_config = lambda: {
      "owner": {
        "chat_id": "99887",
        "timezone": "UTC"
      },
    }
    cfg = mock_config.load_config()
    creds = sched.load_scheduling_credentials(cfg)
    assert creds["owner_id"] == "99887"

  def test_missing_token_file(self, mock_config, monkeypatch):
    # Point ROOT_DIR at a path with no token file
    fake_core_brain = types.ModuleType("core_brain")
    fake_core_brain.ROOT_DIR = "/nonexistent/path"
    monkeypatch.setitem(sys.modules, "core_brain", fake_core_brain)
    cfg = mock_config.load_config()
    with pytest.raises(RuntimeError, match="Cannot load scheduling credentials"):
      sched.load_scheduling_credentials(cfg)

  def test_invalid_timezone(self, mock_config, mock_core_brain_token, monkeypatch):
    mock_config.load_config = lambda: {
      "owner": {
        "owner_chat_id": "123",
        "timezone": "Fake/Zone"
      },
    }
    cfg = mock_config.load_config()
    with pytest.raises(RuntimeError, match="Invalid timezone"):
      sched.load_scheduling_credentials(cfg)

  def test_no_owner_id(self, mock_config, mock_core_brain_token, monkeypatch):
    mock_config.load_config = lambda: {"owner": {}}
    cfg = mock_config.load_config()
    with pytest.raises(RuntimeError, match="No owner_chat_id configured"):
      sched.load_scheduling_credentials(cfg)


# ── format_execution_time_for_display ─────────────────────────────────


class TestFormatExecutionTimeForDisplay:

  def test_utc_to_sgt(self):
    utc_str = "2025-06-15T01:00:00+00:00"
    result = sched.format_execution_time_for_display(utc_str, pytz.timezone("Asia/Singapore"))
    assert "09:00" in result
    # pytz abbreviates Asia/Singapore as '+08', not 'SGT'
    assert "+08" in result

  def test_utc_to_eastern(self):
    utc_str = "2025-06-15T12:00:00+00:00"
    result = sched.format_execution_time_for_display(utc_str, pytz.timezone("US/Eastern"))
    # 12:00 UTC → 08:00 EDT in June
    assert "08:00" in result

  def test_invalid_time_raises(self):
    with pytest.raises(RuntimeError, match="Cannot format execution time"):
      sched.format_execution_time_for_display("not-a-date", pytz.utc)


# ── build_detail_lines ────────────────────────────────────────────────


class TestBuildDetailLines:

  def test_whatsapp_with_recipients(self):
    lines = sched.build_detail_lines(
      "send_whatsapp_message",
      {
        "recipients": ["alice", "bob"],
        "message_text": "hello"
      },
    )
    assert lines == ["To: alice, bob", "Message: hello"]

  def test_whatsapp_with_chat_id_fallback(self):
    lines = sched.build_detail_lines(
      "send_whatsapp_message",
      {
        "chat_id": "999",
        "message_text": "hi"
      },
    )
    assert lines == ["To: 999", "Message: hi"]

  def test_whatsapp_empty_recipients_falls_back(self):
    lines = sched.build_detail_lines(
      "send_whatsapp_message",
      {
        "recipients": [],
        "chat_id": "888",
        "message_text": "hi"
      },
    )
    assert lines == ["To: 888", "Message: hi"]

  def test_telegram_reminder(self):
    lines = sched.build_detail_lines(
      "send_telegram_reminder",
      {"message_text": "Don't forget!"},
    )
    assert lines == ["Reminder: Don't forget!"]

  def test_send_summary(self):
    lines = sched.build_detail_lines(
      "send_summary",
      {"group": "Work Team"},
    )
    assert lines == ["Group: Work Team"]

  def test_llm_task(self):
    lines = sched.build_detail_lines(
      "llm_task",
      {"prompt": "Summarize this"},
    )
    assert lines == ["Task: Summarize this"]

  def test_unknown_action(self):
    lines = sched.build_detail_lines("unknown_action", {"foo": "bar"})
    assert lines == []

  def test_missing_params_defaults(self):
    lines = sched.build_detail_lines(
      "send_telegram_reminder",
      {},
    )
    assert lines == ["Reminder: (empty)"]


# ── build_confirmation_message ────────────────────────────────────────


class TestBuildConfirmationMessage:

  def test_no_cron(self):
    text = sched.build_confirmation_message(
      "abc12",
      "send_telegram_reminder",
      {"message_text": "hello"},
      "2025-06-15 09:00 SGT",
      None,
    )
    assert "<b>📅 Task Scheduled</b>" in text
    assert "ID: abc12" in text
    assert "Action: send_telegram_reminder" in text
    assert "Time: 2025-06-15 09:00 SGT" in text
    assert "Reminder: hello" in text
    assert "Recurrence" not in text

  def test_with_cron(self):
    text = sched.build_confirmation_message(
      "xyz",
      "llm_task",
      {"prompt": "do stuff"},
      "2025-06-15 09:00 SGT",
      "0 10 * * *",
    )
    assert "Recurrence: 0 10 * * *" in text

  def test_html_escaping(self):
    text = sched.build_confirmation_message(
      "id1",
      "send_telegram_reminder",
      {"message_text": "<script>alert('xss')</script>"},
      "2025-06-15 09:00 SGT",
      None,
    )
    assert "&lt;script&gt;" in text
    assert "<script>" not in text


# ── send_telegram_message ─────────────────────────────────────────────


class TestSendTelegramMessage:

  def test_success(self):
    mock_response = MagicMock()
    mock_response.status_code = 200
    with patch("util.scheduling.requests.post", return_value=mock_response) as mock_post:
      sched.send_telegram_message("token", "12345", "hello")
      mock_post.assert_called_once()
      call_kwargs = mock_post.call_args
      assert call_kwargs[1]["json"]["chat_id"] == "12345"
      assert call_kwargs[1]["json"]["text"] == "hello"
      assert call_kwargs[1]["json"]["parse_mode"] == "HTML"

  def test_http_error_raises(self):
    mock_response = MagicMock()
    mock_response.raise_for_status.side_effect = requests_mock_error()
    with patch("util.scheduling.requests.post", return_value=mock_response):
      with pytest.raises(RuntimeError, match="Failed to send confirmation notification"):
        sched.send_telegram_message("token", "12345", "hello")


def requests_mock_error():
  """Return a requests exception for testing."""
  import requests
  return requests.exceptions.HTTPError("500 Server Error")


# ── send_scheduling_confirmation ──────────────────────────────────────


class TestSendSchedulingConfirmation:

  def test_full_flow(self, mock_config, mock_core_brain_token, monkeypatch):
    mock_response = MagicMock()
    mock_response.status_code = 200
    with patch("util.scheduling.requests.post", return_value=mock_response):
      sched.send_scheduling_confirmation(
        "task1",
        "send_telegram_reminder",
        {"message_text": "hi"},
        "2025-06-15T01:00:00+00:00",
        None,
      )
    # No exception = success

  def test_creds_failure_propagates(self, mock_config, monkeypatch):
    # Make credentials fail
    fake_core_brain = types.ModuleType("core_brain")
    fake_core_brain.ROOT_DIR = "/nonexistent"
    monkeypatch.setitem(sys.modules, "core_brain", fake_core_brain)
    with pytest.raises(RuntimeError, match="Cannot load scheduling credentials"):
      sched.send_scheduling_confirmation(
        "task1",
        "send_telegram_reminder",
        {"message_text": "hi"},
        "2025-06-15T01:00:00+00:00",
        None,
      )


# ── handle_schedule_task ──────────────────────────────────────────────


class TestHandleScheduleTask:

  def _make_args(self, action_key, extra=None):
    args = {
      "execution_time": "2025-07-01T10:00:00",
    }
    if extra:
      args.update(extra)
    return args

  def test_telegram_reminder(self, sched_db_path):
    with patch("util.scheduling.send_scheduling_confirmation"):
      result = sched.handle_schedule_task(
        "schedule_telegram_reminder",
        self._make_args("schedule_telegram_reminder", {"message_text": "hi"}),
        "owner1",
        sched_db_path,
      )
      assert "successfully" in result
      assert "ID:" in result

  def test_whatsapp_message(self, sched_db_path):
    with patch("util.scheduling.send_scheduling_confirmation"):
      result = sched.handle_schedule_task(
        "schedule_whatsapp_message",
        self._make_args("schedule_whatsapp_message", {
          "recipients": ["alice"],
          "message_text": "hi",
        }),
        "owner1",
        sched_db_path,
      )
      assert "successfully" in result

  def test_whatsapp_summary(self, sched_db_path):
    with patch("util.scheduling.send_scheduling_confirmation"):
      result = sched.handle_schedule_task(
        "schedule_whatsapp_summary",
        self._make_args("schedule_whatsapp_summary", {"group": "Work"}),
        "owner1",
        sched_db_path,
      )
      assert "successfully" in result

  def test_llm_task(self, sched_db_path):
    with patch("util.scheduling.send_scheduling_confirmation"):
      result = sched.handle_schedule_task(
        "schedule_llm_task",
        self._make_args("schedule_llm_task", {"prompt": "do stuff"}),
        "owner1",
        sched_db_path,
      )
      assert "successfully" in result

  def test_unknown_tool(self):
    result = sched.handle_schedule_task("unknown_tool", {}, "owner1", "dummy.db")
    assert result is None

  def test_missing_execution_time(self):
    result = sched.handle_schedule_task(
      "schedule_telegram_reminder",
      {},
      "owner1",
      "dummy.db",
    )
    assert "execution_time is required" in result

  def test_bad_time_format(self):
    result = sched.handle_schedule_task(
      "schedule_telegram_reminder",
      {"execution_time": "not-a-date"},
      "owner1",
      "dummy.db",
    )
    assert "could not parse" in result

  def test_confirmation_failure_task_still_scheduled(self, sched_db_path):
    with patch(
        "util.scheduling.send_scheduling_confirmation",
        side_effect=RuntimeError("API down"),
    ):
      result = sched.handle_schedule_task(
        "schedule_telegram_reminder",
        self._make_args("schedule_telegram_reminder", {"message_text": "hi"}),
        "owner1",
        sched_db_path,
      )
      assert "Task scheduled" in result
      assert "failed to send confirmation" in result
      # Verify task was still inserted
      conn = sqlite3.connect(sched_db_path)
      cursor = conn.cursor()
      cursor.execute("SELECT COUNT(*) FROM scheduled_tasks WHERE status = 'pending'")
      count = cursor.fetchone()[0]
      conn.close()
      assert count == 1


# ── handle_list_scheduled_tasks ───────────────────────────────────────


class TestHandleListScheduledTasks:

  def test_no_tasks(self, sched_db_path):
    result = sched.handle_list_scheduled_tasks(sched_db_path)
    assert "No pending" in result

  def test_multiple_tasks(self, sched_db_path):
    sched.insert_scheduled_task(
      sched_db_path,
      "t1",
      "o1",
      "2025-07-01T10:00:00+00:00",
      "send_telegram_reminder",
      {"message_text": "a"},
      None,
    )
    sched.insert_scheduled_task(
      sched_db_path,
      "t2",
      "o1",
      "2025-07-02T10:00:00+00:00",
      "llm_task",
      {"prompt": "b"},
      "0 10 * * *",
    )
    result = sched.handle_list_scheduled_tasks(sched_db_path)
    assert "Upcoming Scheduled Tasks" in result
    assert "t1" in result
    assert "t2" in result


# ── handle_cancel_scheduled_task ──────────────────────────────────────


class TestHandleCancelScheduledTask:

  def test_cancels_task(self, sched_db_path):
    sched.insert_scheduled_task(
      sched_db_path,
      "t1",
      "o1",
      "2025-07-01T10:00:00+00:00",
      "send_telegram_reminder",
      {},
      None,
    )
    result = sched.handle_cancel_scheduled_task({"task_id": "t1"}, sched_db_path)
    assert "has been cancelled" in result
    # Verify status changed
    conn = sqlite3.connect(sched_db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT status FROM scheduled_tasks WHERE task_id = ?", ("t1",))
    status = cursor.fetchone()[0]
    conn.close()
    assert status == "cancelled"
