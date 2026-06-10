import requests
import trafilatura
from playwright.sync_api import sync_playwright
import logging

_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
_MAX_CHARS = 12000


def fetch_page_content(url: str) -> str:
  """Attempts to fetch URL via requests, falling back to Playwright if needed."""
  # 1. Try fast Tier 1 (requests)
  try:
    logging.info(f"Fetching page via requests (Tier 1): {url}")
    response = requests.get(url, headers={"User-Agent": _USER_AGENT}, timeout=10)
    if response.status_code == 200:
      markdown = trafilatura.extract(
          response.text,
          output_format="markdown",
          favor_precision=True,
          favor_recall=True,
          include_tables=True,
          include_links=True,
          deduplicate=False,
      )
      if markdown and len(markdown.strip()) > 300:
        return _truncate(markdown)
  except Exception as e:
    logging.warning(f"Tier 1 (requests) failed for {url}: {e}")

  # 2. Try slow Tier 2 (Playwright with system Chrome)
  try:
    logging.info(f"Falling back to Playwright (Tier 2): {url}")
    with sync_playwright() as p:
      browser = p.chromium.launch(channel="chrome", headless=True)
      page = browser.new_page()
      page.goto(url, timeout=15000)
      rendered_html = page.content()
      browser.close()

      markdown = trafilatura.extract(
          rendered_html,
          output_format="markdown",
          favor_precision=True,
          favor_recall=True,
          include_tables=True,
          include_links=True,
          deduplicate=False,
      )
      if markdown:
        return _truncate(markdown)
  except Exception as e:
    logging.error(f"Tier 2 (Playwright) failed for {url}: {e}")
    return f"Error fetching page content: {e}"

  return "Error: Could not extract readable content from the page."


def _truncate(text: str) -> str:
  if len(text) > _MAX_CHARS:
    return text[:_MAX_CHARS] + "\n\n[Content truncated due to length limits...]"
  return text
