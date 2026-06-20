import trafilatura
from absl import app
from playwright.sync_api import sync_playwright


def main(argv):
  del argv

  with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()

    page.goto('https://www.bbc.com/')
    page.wait_for_timeout(5000)

    rendered_html = page.content()

    text = page.inner_text('body')

    browser.close()

  markdown_text = trafilatura.extract(
    rendered_html,
    output_format="markdown",
    favor_precision=True,
    favor_recall=True,
    include_tables=True,
    include_links=True,
    deduplicate=False,
  )
  print(text)
  print(markdown_text)


if __name__ == '__main__':
  app.run(main)
