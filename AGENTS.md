## Code Style

- Python code must use **2-space indentation** (not 4 spaces or tabs).
- Ruff is automatically checked after every file write/edit. If ruff reports issues, fix them before continuing.

## Testing
After every code change that could affect tests, run the full test suite:

    ./v/bin/python -m pytest tools/tests/ util/tests/

If any test fails, fix the issue before moving on. Never leave failing tests.
