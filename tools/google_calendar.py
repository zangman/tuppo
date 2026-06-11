import os
import datetime
import sqlite3
import uuid
import requests
import json
import pytz
import sys
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
import logging

ROOT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT_DIR)
import util.config as config

# If modifying these scopes, delete the file token.json.
SCOPES = ['https://www.googleapis.com/auth/calendar.readonly', 'https://www.googleapis.com/auth/calendar.events', 'https://www.googleapis.com/auth/gmail.modify']
CREDENTIALS_FILE = os.path.join(ROOT_DIR, 'credentials.json')
TOKEN_FILE = os.path.join(ROOT_DIR, 'token.json')


def _get_owner() -> dict:
    """Get the owner section from config.yaml."""
    return config.load_config().get('owner', {})


def _get_owner_chat_id() -> str:
    return _get_owner().get('owner_chat_id', _get_owner().get('chat_id', ''))


def _get_owner_timezone() -> str:
    return _get_owner().get('timezone', 'UTC')


def _get_home_calendar_id() -> str:
    return _get_owner().get('home_calendar_id', '')


def _resolve_calendar_id(calendar_id: str) -> str:
    """Resolve natural calendar name to actual Google Calendar ID."""
    if calendar_id == "primary":
        return "primary"
    if calendar_id == "home":
        home_id = _get_home_calendar_id()
        if home_id:
            return home_id
        logging.warning("home_calendar_id not set in config, falling back to primary")
        return "primary"
    return calendar_id  # passthrough explicit ID


def _notify_calendar_auth_needed(auth_url: str):
    """Send a Telegram notification with the Google Calendar auth URL."""
    try:
        with open(os.path.join(ROOT_DIR, 'token'), 'r') as f:
            bot_token = f.read().strip()
        owner_id = _get_owner_chat_id()

        message = (
            "⚠️ <b>Google Calendar token expired!</b>\n\n"
            "To renew, <a href='{}'>click here to authorize</a>.\n\n"
            "After authorizing, the bot will automatically save the new token."
        ).format(auth_url)

        requests.post(
            f"https://api.telegram.org/bot{bot_token}/sendMessage",
            json={"chat_id": owner_id, "text": message, "parse_mode": "HTML"}
        )
        logging.info("Sent calendar auth notification to Telegram")
    except Exception as e:
        logging.error(f"Failed to send calendar auth notification: {e}")


class TelegramNotificationPrompt:
    def __init__(self, callback_fn):
        self.callback_fn = callback_fn

    def format(self, url):
        self.callback_fn(url)
        return f"Authorization URL sent to Telegram. Please check your Telegram. URL: {url}"

    def __bool__(self):
        return True

def get_calendar_service():
    """
    Authenticates the user and returns the Google Calendar service object.
    """
    creds = None
    # The file token.json stores the user's access and refresh tokens.
    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)

    # If there are no (valid) credentials available, let the user log in.
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except Exception as e:
                logging.error(f"Error refreshing token: {e}")
                creds = None

        if not creds:
            if not os.path.exists(CREDENTIALS_FILE):
                raise FileNotFoundError(f"credentials.json not found at {CREDENTIALS_FILE}. Please download it from Google Cloud Console.")

            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
            flow.redirect_uri = 'http://localhost:8099/'

            prompt = TelegramNotificationPrompt(_notify_calendar_auth_needed)

            creds = flow.run_local_server(
                port=8099,
                open_browser=False,
                authorization_prompt_message=prompt,
                access_type='offline',
                include_granted_scopes='true'
            )

        with open(TOKEN_FILE, 'w') as token:
            token.write(creds.to_json())

    return build('calendar', 'v3', credentials=creds)

def check_owner_availability(time_min=None, time_max=None) -> str:
    """
    Returns a sanitized list of busy blocks from the primary and home calendars.
    Used for external contacts to check availability without seeing private details.
    """
    try:
        service = get_calendar_service()
        owner = _get_owner()
        owner_tz = pytz.timezone(owner.get('timezone', 'UTC'))

        if not time_min or not time_max:
            now_owner = datetime.datetime.now(owner_tz)
            today_start = now_owner.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
            today_end = now_owner.replace(hour=23, minute=59, second=59, microsecond=0).isoformat()
            time_min = time_min or today_start
            time_max = time_max or today_end

        # Resolve calendars to check
        calendars_to_check = ['primary']
        home_cal_id = owner.get('home_calendar_id')
        if home_cal_id:
            calendars_to_check.append(home_cal_id)

        logging.info(f"Checking availability for {calendars_to_check} from {time_min} to {time_max}")

        all_events = []
        for cal_id in calendars_to_check:
            try:
                events_result = service.events().list(
                    calendarId=cal_id, 
                    timeMin=time_min, 
                    timeMax=time_max,
                    singleEvents=True,
                    orderBy='startTime'
                ).execute()
                all_events.extend(events_result.get('items', []))
            except Exception as e:
                logging.error(f"Error fetching availability for {cal_id}: {e}")
        
        if not all_events:
            return "The owner is currently free for the specified time range."

        # Sort combined events by start time
        all_events.sort(key=lambda x: x['start'].get('dateTime', x['start'].get('date')))

        output = ["=== Owner Availability (Sanitized) ==="]
        for event in all_events:
            start = event['start'].get('dateTime', event['start'].get('date'))
            end = event['end'].get('dateTime', event['end'].get('date'))
            output.append(f"- {start} to {end}: BUSY")

        return "\n".join(output)
    except Exception as e:
        logging.error(f"Google Calendar Availability Error: {e}")
        return f"Error checking availability: {e}"

def propose_calendar_event(summary: str = None, start_iso: str = None, end_iso: str = None, description: str = "", requester_id: str = "Unknown") -> str:
    """
    Proposes a new event to the owner via Telegram.
    The event is NOT created in the calendar until the owner approves it on Telegram.
    """
    try:
        # 1. Save proposal to DB
        proposal_id = str(uuid.uuid4())[:8]
        conn = sqlite3.connect(os.path.join(ROOT_DIR, 'whatsapp.db'))
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO event_proposals (proposal_id, summary, start_iso, end_iso, description, requester_id) VALUES (?, ?, ?, ?, ?, ?)",
            (proposal_id, summary, start_iso, end_iso, description, requester_id)
        )
        conn.commit()
        conn.close()

        # 2. Send Telegram Notification
        with open(os.path.join(ROOT_DIR, 'token'), 'r') as f:
            bot_token = f.read().strip()

        owner_id = _get_owner_chat_id()

        if not owner_id or owner_id == "SET_ME":
            return "Error: Owner Chat ID not configured in profile. Please set owner_chat_id."

        import html
        # Look up display name from contacts table
        display_name = requester_id
        try:
            conn = sqlite3.connect(os.path.join(ROOT_DIR, 'whatsapp.db'), timeout=10.0)
            cursor = conn.cursor()
            cursor.execute("SELECT display_name FROM contacts WHERE chat_id = ? OR chat_id = ?", [requester_id, requester_id.replace('@c.us', '').replace('@lid', '')])
            row = cursor.fetchone()
            conn.close()
            if row:
                display_name = row[0]
        except Exception:
            pass

        text = (
            f"<b>🔔 EVENT PROPOSAL RECEIVED</b>\n\n"
            f"👤 <b>From</b>: {html.escape(display_name)}\n"
            f"📅 <b>Event</b>: {html.escape(summary or 'No Title')}\n"
            f"⏰ <b>Time</b>: {html.escape(start_iso)} to {html.escape(end_iso)}\n"
            f"📝 <b>Note</b>: {html.escape(description or 'No description')}"
        )

        keyboard = {
            "inline_keyboard": [[
                {"text": "Approve ✅", "callback_data": f"app_{proposal_id}"},
                {"text": "Reject ❌", "callback_data": f"rej_{proposal_id}"}
            ]]
        }

        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        payload = {
            "chat_id": owner_id,
            "text": text,
            "parse_mode": "HTML",
            "reply_markup": json.dumps(keyboard)
        }
        
        resp = requests.post(url, json=payload)
        logging.info(f"Telegram API Response for Proposal {proposal_id}: {resp.status_code} - {resp.text}")
        if resp.status_code == 200:
            return f"Proposal sent to owner for approval (ID: {proposal_id})."
        else:
            return f"Error sending Telegram notification: {resp.text}"

    except Exception as e:
        logging.error(f"Propose Event Error: {e}")
        return f"Error proposing event: {e}"

def list_user_calendars() -> str:
    """
    List all calendars the user has access to, including their IDs.
    """
    try:
        service = get_calendar_service()
        calendar_list = service.calendarList().list().execute()
        calendars = calendar_list.get('items', [])

        if not calendars:
            return "No calendars found."

        output = ["=== Your Google Calendars ==="]
        for cal in calendars:
            output.append(f"- {cal['summary']} (ID: {cal['id']})")
        
        return "\n".join(output)
    except Exception as e:
        logging.error(f"Google Calendar ListCalendars Error: {e}")
        return f"Error retrieving calendars: {e}"

def list_calendar_events(time_min=None, time_max=None) -> str:
    """
    Fetch upcoming events from all calendars (primary + home) combined.
    time_min and time_max should be in ISO format (e.g., 2026-05-28T00:00:00Z).
    """
    try:
        service = get_calendar_service()
        owner = _get_owner()

        calendars_to_query = ["primary"]
        home_id = owner.get('home_calendar_id')
        if home_id:
            calendars_to_query.append(home_id)

        owner_tz = pytz.timezone(owner.get('timezone', 'UTC'))

        def _ensure_tz(iso_str):
            """If iso_str has no timezone info, inject the owner's timezone."""
            if not iso_str:
                return iso_str
            # Has timezone if it ends with Z or contains +/after the T
            if 'Z' in iso_str or '+' in iso_str.split('T', 1)[-1]:
                return iso_str
            # Naive timestamp — localize it
            dt = datetime.datetime.fromisoformat(iso_str)
            return owner_tz.localize(dt).isoformat()

        if not time_min or not time_max:
            now_owner = datetime.datetime.now(owner_tz)
            today_start = now_owner.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
            today_end = now_owner.replace(hour=23, minute=59, second=59, microsecond=0).isoformat()
            time_min = time_min or today_start
            time_max = time_max or today_end
        else:
            time_min = _ensure_tz(time_min)
            time_max = _ensure_tz(time_max)

        # Map calendar IDs to display names
        cal_names = {"primary": "Primary"}
        if home_id:
            cal_names[home_id] = "Home"

        all_events = []
        for cid in calendars_to_query:
            try:
                events_result = service.events().list(
                    calendarId=cid,
                    timeMin=time_min,
                    timeMax=time_max,
                    singleEvents=True,
                    orderBy='startTime'
                ).execute()

                events = events_result.get('items', [])
                for event in events:
                    event['_calendar_id'] = cid
                    all_events.append(event)
            except Exception as e:
                logging.error(f"Error fetching events for calendar {cid}: {e}")

        if not all_events:
            return "No events found in the specified time range."

        all_events.sort(key=lambda x: x['start'].get('dateTime', x['start'].get('date')))

        output = [f"=== Calendar Events ({len(calendars_to_query)} calendars) ==="]
        for event in all_events:
            start = event['start'].get('dateTime', event['start'].get('date'))
            summary = event.get('summary', 'No Title')
            description = event.get('description', 'No description')
            cal_id = event['_calendar_id']
            cal_name = cal_names.get(cal_id, cal_id)
            event_id = event.get('id', 'N/A')
            output.append(f"- [{cal_name}] {start}: {summary} (ID: {event_id}, {description})")

        return "\n".join(output)
    except Exception as e:
        logging.error(f"Google Calendar List Error: {e}")
        return f"Error retrieving events: {e}"

def create_calendar_event(calendar_id='primary', summary: str = None, start_iso: str = None, end_iso: str = None, description: str = "") -> str:
    """
    Create a new event on a specific calendar.
    calendar_id: 'primary', 'home', or explicit Google Calendar ID.
    start_iso and end_iso must be in ISO format.
    """
    try:
        service = get_calendar_service()
        calendar_id = _resolve_calendar_id(calendar_id)
        timezone = _get_owner_timezone()

        def sanitize_iso(iso_str):
            if not iso_str: return None
            return iso_str.replace('Z', '').split('+')[0]

        start_iso = sanitize_iso(start_iso)
        end_iso = sanitize_iso(end_iso)

        event = {
            'summary': summary,
            'description': description,
            'start': {
                'dateTime': start_iso,
                'timeZone': timezone,
            },
            'end': {
                'dateTime': end_iso,
                'timeZone': timezone,
            },
        }

        event = service.events().insert(calendarId=calendar_id, body=event).execute()
        return f"Event created successfully in {calendar_id}! Link: {event.get('htmlLink')}"
    except Exception as e:
        logging.error(f"Google Calendar Create Error: {e}")
        return f"Error creating event: {e}"

def delete_calendar_event(calendar_id='primary', event_id: str = None) -> str:
    """
    Delete an event from a specific calendar.
    calendar_id: 'primary', 'home', or explicit Google Calendar ID.
    event_id is the unique identifier of the event to be deleted.
    """
    if not event_id:
        return "Error: An event_id is required to delete an event."

    try:
        service = get_calendar_service()
        calendar_id = _resolve_calendar_id(calendar_id)
        service.events().delete(calendarId=calendar_id, eventId=event_id).execute()
        return f"Event {event_id} has been successfully deleted from {calendar_id}."
    except Exception as e:
        logging.error(f"Google Calendar Delete Error: {e}")
        return f"Error deleting event: {e}"

def update_calendar_event(calendar_id='primary', event_id: str = None, summary: str = None, start_iso: str = None, end_iso: str = None, description: str = None) -> str:
    """
    Update an existing event on a specific calendar.
    calendar_id: 'primary', 'home', or explicit Google Calendar ID.
    event_id is the unique identifier of the event to be updated.
    Other parameters (summary, start_iso, end_iso, description) are optional; only provided fields will be updated.
    """
    if not event_id:
        return "Error: An event_id is required to update an event."

    try:
        service = get_calendar_service()
        calendar_id = _resolve_calendar_id(calendar_id)
        timezone = _get_owner_timezone()

        event_body = {}
        if summary:
            event_body['summary'] = summary
        if description:
            event_body['description'] = description
        
        if start_iso:
            event_body['start'] = {'dateTime': start_iso, 'timeZone': timezone}
        if end_iso:
            event_body['end'] = {'dateTime': end_iso, 'timeZone': timezone}

        if not event_body:
            return "No updates provided for the event."

        updated_event = service.events().patch(
            calendarId=calendar_id, 
            eventId=event_id, 
            body=event_body
        ).execute()
        
        return f"Event {event_id} updated successfully in {calendar_id}! Link: {updated_event.get('htmlLink')}"
    except Exception as e:
        logging.error(f"Google Calendar Update Error: {e}")
        return f"Error updating event: {e}"
