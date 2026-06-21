"""Tests for util/message.py."""

from unittest.mock import MagicMock

from util.message import _split_markdown, compose_long_message

# ── TestSplitMarkdown ────────────────────────────────────────────────


class TestSplitMarkdown:

  def test_short_text_returns_single_chunk(self):
    text = "Hello world"
    assert _split_markdown(text) == ["Hello world"]

  def test_text_at_exact_boundary(self):
    text = "x" * 3500
    assert _split_markdown(text) == [text]

  def test_single_paragraph_over_max_len(self):
    text = "x" * 4000
    assert len(_split_markdown(text)) == 2
    assert all(len(c) <= 3500 for c in _split_markdown(text))

  def test_two_short_paragraphs_fit_in_one_chunk(self):
    p1 = "a" * 100
    p2 = "b" * 100
    text = f"{p1}\n\n{p2}"
    assert len(_split_markdown(text)) == 1

  def test_paragraphs_exceeding_max_len_split(self):
    p1 = "a" * 2000
    p2 = "b" * 2000
    text = f"{p1}\n\n{p2}"
    chunks = _split_markdown(text)
    assert len(chunks) == 2
    assert all(len(c) <= 3500 for c in chunks)

  def test_single_line_over_max_len_hard_split(self):
    text = "x" * 5000
    chunks = _split_markdown(text)
    assert len(chunks) == 2
    assert all(len(c) <= 3500 for c in chunks)

  def test_empty_string(self):
    assert _split_markdown("") == [""]

  def test_multiline_paragraph_splits_by_lines(self):
    # Two lines, each 2000 chars, separated by \n (not \n\n)
    line1 = "a" * 2000
    line2 = "b" * 2000
    text = f"{line1}\n{line2}"
    chunks = _split_markdown(text)
    assert len(chunks) == 2
    assert all(len(c) <= 3500 for c in chunks)

  def test_many_small_paragraphs_grouped(self):
    paragraphs = ["p" * 500 for _ in range(10)]
    text = "\n\n".join(paragraphs)  # 5000 + separators total
    chunks = _split_markdown(text)
    assert len(chunks) >= 2
    assert all(len(c) <= 3500 for c in chunks)


# ── TestComposeLongMessage ───────────────────────────────────────────


class TestComposeLongMessage:

  def test_short_text_single_chunk(self):
    result = compose_long_message("Hello world")
    assert len(result) == 1
    text, entities, markup = result[0]
    assert "Hello world" in text
    assert markup is None

  def test_long_text_multiple_chunks(self):
    text = "x" * 8000
    result = compose_long_message(text)
    assert len(result) == 3
    # Markup should be None on all chunks when no reply_markup given
    for _, _, markup in result:
      assert markup is None

  def test_show_tps_appends_stats_to_last_chunk(self):
    result = compose_long_message("short", show_tps=True, pp=1.5, tp=10.0)
    text, _, _ = result[0]
    assert "pp: 1.5" in text
    assert "tp: 10.0" in text

  def test_show_tps_without_pp_tp_no_stats(self):
    result = compose_long_message("short", show_tps=True)
    text, _, _ = result[0]
    assert "pp:" not in text
    assert "tp:" not in text

  def test_reply_markup_only_on_last_chunk(self):
    markup = MagicMock()
    text = "x" * 8000
    result = compose_long_message(text, reply_markup=markup)
    assert len(result) == 3
    # First chunk: no markup
    _, _, first_markup = result[0]
    assert first_markup is None
    # Last chunk: has markup
    _, _, last_markup = result[-1]
    assert last_markup is markup

  def test_reply_markup_on_single_chunk(self):
    markup = MagicMock()
    result = compose_long_message("short", reply_markup=markup)
    assert len(result) == 1
    _, _, chunk_markup = result[0]
    assert chunk_markup is markup

  def test_empty_input_returns_empty_list(self):
    result = compose_long_message("")
    assert result == []

  def test_whitespace_only_returns_empty_list(self):
    result = compose_long_message("   \n  \n  ")
    assert result == []

  def test_markdown_entities_present(self):
    result = compose_long_message("**bold** and *italic*")
    assert len(result) == 1
    text, entities, _ = result[0]
    assert len(entities) > 0

  def test_tps_not_appended_to_non_last_chunk(self):
    text = "x" * 8000
    result = compose_long_message(text, show_tps=True, pp=2.0, tp=20.0)
    assert len(result) == 3
    first_text, _, _ = result[0]
    assert "pp:" not in first_text
    last_text, _, _ = result[-1]
    assert "pp: 2.0" in last_text
