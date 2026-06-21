import telegramify_markdown as tm


def _split_markdown(text, max_len=3500):
  if len(text) <= max_len:
    return [text]

  chunks = []
  current_chunk = []
  current_len = 0

  paragraphs = text.split('\n\n')
  for p in paragraphs:
    if len(p) > max_len:
      if current_chunk:
        chunks.append('\n\n'.join(current_chunk))
        current_chunk = []
        current_len = 0

      lines = p.split('\n')
      for line in lines:
        if len(line) > max_len:
          if current_chunk:
            chunks.append('\n'.join(current_chunk))
            current_chunk = []
            current_len = 0
          for i in range(0, len(line), max_len):
            chunks.append(line[i:i + max_len])
        else:
          if current_len + len(line) + 1 > max_len:
            chunks.append('\n'.join(current_chunk))
            current_chunk = [line]
            current_len = len(line)
          else:
            current_chunk.append(line)
            current_len += len(line) + 1
    else:
      if current_len + len(p) + 2 > max_len:
        if current_chunk:
          chunks.append('\n\n'.join(current_chunk))
        current_chunk = [p]
        current_len = len(p)
      else:
        current_chunk.append(p)
        current_len += len(p) + 2

  if current_chunk:
    chunks.append('\n\n'.join(current_chunk))

  return chunks


def compose_long_message(markdown_text, show_tps=False, pp=None, tp=None, reply_markup=None):
  """Split long markdown into sendable chunks.

  Args:
    markdown_text: The raw markdown text to split.
    show_tps: If True, append performance stats (pp/tp) to the last chunk.
    pp: Preprocessing time in seconds (only used if show_tps is True).
    tp: Total processing time in seconds (only used if show_tps is True).
    reply_markup: Optional InlineKeyboardMarkup to attach to the last chunk.

  Returns:
    A list of (text, entities, markup) tuples, one per chunk, where:
      - text (str): The Telegram-formatted text (markdown converted via
        telegramify-markdown). Empty chunks are dropped.
      - entities (list[dict]): Telegram message entity dicts (from
        telegramify-markdown) corresponding to the text.
      - markup (InlineKeyboardMarkup | None): The reply_markup on the
        final chunk, or None for all preceding chunks.
    The list is empty if the input produces no non-empty chunks.
  """
  chunks = _split_markdown(markdown_text, max_len=3500)
  result = []
  for i, chunk in enumerate(chunks):
    chat_response, entities = tm.convert(chunk)
    if i == len(chunks) - 1 and show_tps and pp is not None and tp is not None:
      chat_response = f'{chat_response} (pp: {round(pp,2)}, tp: {round(tp,2)})'

    effective_markup = reply_markup if i == len(chunks) - 1 else None

    if chat_response.strip():
      result.append((chat_response, [e.to_dict() for e in entities], effective_markup))
  return result
