import os
import re
import types

import notes
import pytest
from notes import _get_notes_path, save_note


def _make_fake_config(notes_path=None):
  """Build a fake config module with a controlled load_config."""
  fake_config = types.ModuleType("fake_config")
  cfg = {}
  if notes_path is not None:
    cfg["notes"] = {"path": notes_path}
  fake_config.load_config = lambda: cfg
  return fake_config


@pytest.fixture
def mock_default_config(monkeypatch):
  """No notes.path in config (tests the default path)."""
  fake = _make_fake_config()
  monkeypatch.setattr(notes, "config", fake)


@pytest.fixture
def mock_config_with_path(tmp_path, monkeypatch):
  """Notes path points to a temp dir. Returns the resolved path string."""
  notes_file = str(tmp_path / "my_notes.md")
  fake = _make_fake_config(notes_path=notes_file)
  monkeypatch.setattr(notes, "config", fake)
  return notes_file


# ── Helpers ──────────────────────────────────────────────────────────


def _read_lines(path):
  with open(path, encoding="utf-8") as f:
    return f.read().splitlines()


# ── Path resolution ──────────────────────────────────────────────────


class TestGetNotesPath:

  def test_default_path(self, mock_default_config):
    assert _get_notes_path() == os.path.expanduser("~/Documents/notes.md")

  def test_configured_path(self, mock_config_with_path):
    assert _get_notes_path() == mock_config_with_path


# ── save_note happy path ─────────────────────────────────────────────


class TestSaveNote:

  def test_creates_file(self, mock_config_with_path):
    save_note("first note")
    assert os.path.isfile(mock_config_with_path)

  def test_appends_to_existing(self, mock_config_with_path):
    save_note("note one")
    save_note("note two")
    lines = _read_lines(mock_config_with_path)
    assert len(lines) == 2
    assert "note one" in lines[0]
    assert "note two" in lines[1]

  def test_timestamp_format(self, mock_config_with_path):
    save_note("test")
    line = _read_lines(mock_config_with_path)[0]
    # YYYY-MM-DD HH:MM:SS | <text>
    assert re.match(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} \| test", line)

  def test_return_value(self, mock_default_config):
    # Uses default path — just check the return string format
    result = save_note("hello")
    assert "Note saved:" in result
    assert re.search(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", result)

  def test_special_characters(self, mock_config_with_path):
    save_note('quotes "and" pipes | and emojis 🎉')
    lines = _read_lines(mock_config_with_path)
    assert 'quotes "and" pipes | and emojis 🎉' in lines[0]

  def test_multiple_saves(self, mock_config_with_path):
    for i in range(5):
      save_note(f"note {i}")
    lines = _read_lines(mock_config_with_path)
    assert len(lines) == 5


# ── Error handling ───────────────────────────────────────────────────


class TestSaveNoteErrors:

  @pytest.mark.skipif(os.geteuid() == 0, reason="root can write anywhere")
  def test_permission_error_on_write(self, tmp_path, monkeypatch):
    """Unwritable file → PermissionError is raised."""
    notes_file = str(tmp_path / "locked.md")
    fake = _make_fake_config(notes_path=notes_file)
    monkeypatch.setattr(notes, "config", fake)

    # Create the file and make it unwritable
    with open(notes_file, "w") as f:
      f.write("existing\n")
    os.chmod(notes_file, 0o000)
    try:
      with pytest.raises(PermissionError):
        save_note("should fail")
    finally:
      os.chmod(notes_file, 0o644)  # cleanup so tmpdir can be removed

  @pytest.mark.skipif(os.geteuid() == 0, reason="root can write anywhere")
  def test_permission_error_on_directory(self, tmp_path, monkeypatch):
    """Unwritable parent dir → PermissionError is raised."""
    locked_dir = tmp_path / "locked"
    locked_dir.mkdir()
    notes_file = str(locked_dir / "sub" / "notes.md")
    fake = _make_fake_config(notes_path=notes_file)
    monkeypatch.setattr(notes, "config", fake)

    os.chmod(locked_dir, 0o000)
    try:
      with pytest.raises(PermissionError):
        save_note("should fail")
    finally:
      os.chmod(locked_dir, 0o755)

  def test_default_path_when_config_missing(self, mock_default_config):
    """Missing notes.path key → uses ~/Documents/notes.md."""
    assert _get_notes_path() == os.path.expanduser("~/Documents/notes.md")
