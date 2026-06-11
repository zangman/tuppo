import os
import datetime
import pytz
import logging
import email.message
import base64
from bs4 import BeautifulSoup
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

ROOT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import util.config as config

CREDENTIALS_FILE = os.path.join(ROOT_DIR, 'credentials.json')
TOKEN_FILE = os.path.join(ROOT_DIR, 'token.json')


def _get_owner_timezone():
    """Get owner timezone from config.yaml."""
    return config.load_config().get('owner', {}).get('timezone', 'UTC')


def _rfc2822_to_local(rfc2822_str):
    """Convert an RFC 2822 date string to local timezone."""
    try:
        # Parse RFC 2822 date (e.g. "Tue, 10 Jun 2025 13:41:00 -0000")
        dt = datetime.datetime.strptime(rfc2822_str, "%a, %d %b %Y %H:%M:%S %z")
        local_tz = pytz.timezone(_get_owner_timezone())
        return dt.astimezone(local_tz).strftime("%Y-%m-%d %H:%M %Z (%z)")
    except Exception:
        return rfc2822_str


def get_gmail_service():
    """Get a Gmail API service object, reusing the same OAuth token as calendar."""
    creds = None
    if os.path.exists(TOKEN_FILE):
        try:
            with open(TOKEN_FILE, 'r') as f:
                creds = Credentials.from_authorized_user_file(TOKEN_FILE)
        except Exception as e:
            logging.error(f"Failed to load Gmail credentials: {e}")
            return None

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
                with open(TOKEN_FILE, 'w') as f:
                    f.write(creds.to_json())
            except Exception as e:
                return f"Gmail API error: Token expired and refresh failed. Please re-auth by running setup_auth.py."
        else:
            return "Gmail API error: No valid credentials. Please run setup_auth.py to authenticate."

    try:
        return build('gmail', 'v1', credentials=creds)
    except Exception as e:
        return f"Gmail API error: {e}"


def check_inbox(max_results: int = 10, query: str = None) -> str:
    """List unread emails. Fetches message IDs, then retrieves each message for headers."""
    max_results = min(max_results, 50)
    service = get_gmail_service()
    if isinstance(service, str):
        return service

    try:
        q = f"is:unread {query}" if query else "is:unread"
        # Fetch message IDs first, then get full details for headers
        # Note: avoid 'format' kwarg — it shadows Python builtin and breaks on some versions
        results = service.users().messages().list(
            userId='me',
            maxResults=max_results,
            q=q
        ).execute()

        messages = results.get('messages', [])
        if not messages:
            return "No unread emails in your inbox."

        # Fetch each message (format defaults to 'full')
        lines = [f"Unread emails ({len(messages)} of {results.get('resultSizeEstimate', '?')} total):"]
        for msg_id_obj in messages:
            msg_id = msg_id_obj['id']
            msg = service.users().messages().get(
                userId='me', id=msg_id
            ).execute()

            payload = msg.get('payload', {})
            headers = payload.get('headers', [])
            subject = ''
            frm = ''
            date = ''
            snippet = msg.get('snippet', '(no preview)')
            for h in headers:
                if h['name'] == 'Subject':
                    subject = h['value'] or '(no subject)'
                elif h['name'] == 'From':
                    frm = h['value']
                elif h['name'] == 'Date':
                    date = _rfc2822_to_local(h['value'])

            # Truncate long previews
            preview = (snippet[:150] + '...') if len(snippet) > 150 else snippet

            lines.append(
                f"  [{msg_id}] {date}\n"
                f"    From: {frm}\n"
                f"    Subject: {subject}\n"
                f"    Preview: {preview}\n"
            )

        return '\n'.join(lines)

    except Exception as e:
        logging.error(f"Gmail check_inbox error: {e}")
        return f"Gmail API error: {e}"


def read_email(message_id: str) -> str:
    """Read full email content, stripping HTML and returning plain text."""
    service = get_gmail_service()
    if isinstance(service, str):
        return service

    try:
        msg = service.users().messages().get(
            userId='me', id=message_id
        ).execute()

        # Extract headers
        headers = msg.get('payload', {}).get('headers', [])
        subject = ''
        frm = ''
        to = ''
        date = ''
        for h in headers:
            if h['name'] == 'Subject':
                subject = h['value'] or '(no subject)'
            elif h['name'] == 'From':
                frm = h['value']
            elif h['name'] == 'To':
                to = h['value']
            elif h['name'] == 'Date':
                date = _rfc2822_to_local(h['value'])

        # Extract body from MIME parts
        body = _extract_body(msg.get('payload', {}))
        body = (body[:2000] + '\n\n[Message truncated]') if len(body) > 2000 else body

        return (
            f"From: {frm}\nTo: {to}\nDate: {date}\nSubject: {subject}\n\n"
            f"{body}"
        )

    except Exception as e:
        logging.error(f"Gmail read_email error: {e}")
        return f"Gmail API error: {e}"


def _extract_body(payload) -> str:
    """Recursively extract plain text body from a Gmail message payload."""
    parts = payload.get('parts', [])

    for part in parts:
        mime_type = part.get('mimeType', '')
        data = part.get('body', {}).get('data', '')

        if mime_type == 'text/plain' and data:
            decoded = base64.urlsafe_b64decode(data).decode('utf-8', errors='replace')
            # Clean up quoted-printable or long lines
            return ' '.join(decoded.split())
        elif mime_type == 'text/html' and data:
            decoded = base64.urlsafe_b64decode(data).decode('utf-8', errors='replace')
            soup = BeautifulSoup(decoded, 'html.parser')
            text = soup.get_text(separator='\n', strip=True)
            return ' '.join(text.split())
        elif 'multipart' in mime_type:
            # Recurse into subparts, prefer plain text over html
            recursive = _extract_body(part)
            if recursive:
                return recursive

    # Fallback: check top-level body (sometimes inline messages have no parts)
    data = payload.get('body', {}).get('data', '')
    if data:
        decoded = base64.urlsafe_b64decode(data).decode('utf-8', errors='replace')
        mime_type = payload.get('mimeType', 'text/plain')
        if mime_type == 'text/html':
            soup = BeautifulSoup(decoded, 'html.parser')
            text = soup.get_text(separator='\n', strip=True)
            return ' '.join(text.split())
        return ' '.join(decoded.split())

    return '(empty message)'


def mark_emails_read(message_ids: list[str]) -> str:
    """Mark Gmail messages as read by removing the UNREAD label."""
    if not message_ids:
        return "No messages to mark as read."

    service = get_gmail_service()
    if isinstance(service, str):
        return service

    try:
        service.users().messages().batchModify(
            userId='me',
            body={
                'ids': message_ids,
                'removeLabelIds': ['UNREAD']
            }
        ).execute()
        return f"Marked {len(message_ids)} email(s) as read."
    except Exception as e:
        logging.error(f"Gmail mark_emails_read error: {e}")
        return f"Gmail API error: {e}"
