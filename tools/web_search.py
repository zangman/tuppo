from exa_py import Exa

_CLIENT = None


def _get_client():
    global _CLIENT
    if _CLIENT is None:
        with open('exa_token') as f:
            _CLIENT = Exa(api_key=f.read().strip())
    return _CLIENT


def search(query: str, num_results: int = 5) -> str:
    """Search the web and return results as a formatted string."""
    num_results = min(max(1, num_results), 10)
    try:
        client = _get_client()
        response = client.search(
            query,
            num_results=num_results,
            contents={"highlights": True},
        )
        return _format_results(response.results)
    except Exception as e:
        return f"Search error: {e}"


def _format_results(results) -> str:
    lines = []
    for i, r in enumerate(results, 1):
        header = f"{i}. {r.title}"
        if r.author:
            header += f" — {r.author}"
        if r.published_date:
            header += f" ({r.published_date})"
        lines.append(header)
        lines.append(f"   {r.url}")
        if r.highlights:
            for h in r.highlights:
                lines.append(f"   • {h.strip()}")
        lines.append("")
    return "\n".join(lines).rstrip()
