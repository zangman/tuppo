import logging
import os
import sys

import requests

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import util.config as config


def _get_searxng_url() -> str:
    return config.load_config().get('searxng', {}).get('url', 'http://localhost:8081/search')


def search(query: str, num_results: int = 5) -> str:
    """Search the web via local SearXNG and return results as a formatted string."""
    num_results = min(max(1, num_results), 10)

    try:
        response = requests.post(
            _get_searxng_url(),
            data={
                "q": query,
                "format": "json"
            },
            timeout=10
        )

        if response.status_code != 200:
            return f"Search error: SearXNG returned status code {response.status_code}"

        data = response.json()
        results = data.get("results", [])[:num_results]

        if not results:
            return "No search results found."

        return _format_results(results)

    except Exception as e:
        logging.error(f"SearXNG query failed: {e}")
        return f"Search error: {e}"

def _format_results(results) -> str:
    lines = []
    for i, r in enumerate(results, 1):
        url = r.get("url", "")
        title = r.get("title", "Untitled")
        content = r.get("content", "")

        header = f"{i}. {title}"
        lines.append(header)
        lines.append(f"   {url}")
        if content:
            lines.append(f"   • {content.strip()}")
        lines.append("")

    return "\n".join(lines).rstrip()
