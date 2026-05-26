from datetime import datetime, timedelta

import pytz
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from config import (
    GOOGLE_CALENDAR_ID,
    GOOGLE_CLIENT_ID,
    GOOGLE_CLIENT_SECRET,
    GOOGLE_REFRESH_TOKEN,
    TIMEZONE,
)

SCOPES = ["https://www.googleapis.com/auth/calendar"]


def _get_service():
    creds = Credentials(
        token=None,
        refresh_token=GOOGLE_REFRESH_TOKEN,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=GOOGLE_CLIENT_ID,
        client_secret=GOOGLE_CLIENT_SECRET,
        scopes=SCOPES,
    )
    creds.refresh(Request())
    return build("calendar", "v3", credentials=creds)


def get_events(start_date: datetime = None, days: int = 7) -> list:
    service = _get_service()
    tz = pytz.timezone(TIMEZONE)

    if start_date is None:
        start_date = datetime.now(tz).replace(hour=0, minute=0, second=0, microsecond=0)

    end_date = start_date + timedelta(days=days)

    result = service.events().list(
        calendarId=GOOGLE_CALENDAR_ID,
        timeMin=start_date.isoformat(),
        timeMax=end_date.isoformat(),
        singleEvents=True,
        orderBy="startTime",
    ).execute()

    return result.get("items", [])


def create_event(
    summary: str,
    start_dt: datetime,
    end_dt: datetime,
    description: str = None,
    recurrence: list = None,
) -> dict:
    service = _get_service()
    event = {
        "summary": summary,
        "start": {"dateTime": start_dt.isoformat(), "timeZone": TIMEZONE},
        "end": {"dateTime": end_dt.isoformat(), "timeZone": TIMEZONE},
    }
    if description:
        event["description"] = description
    if recurrence:
        event["recurrence"] = recurrence
    return service.events().insert(calendarId=GOOGLE_CALENDAR_ID, body=event).execute()


def update_event(event_id: str, updates: dict) -> dict:
    service = _get_service()
    event = service.events().get(calendarId=GOOGLE_CALENDAR_ID, eventId=event_id).execute()
    event.update(updates)
    return service.events().update(calendarId=GOOGLE_CALENDAR_ID, eventId=event_id, body=event).execute()


def delete_event(event_id: str) -> None:
    service = _get_service()
    service.events().delete(calendarId=GOOGLE_CALENDAR_ID, eventId=event_id).execute()


def format_events_for_prompt(events: list) -> str:
    if not events:
        return "Nenhum evento nos próximos dias."

    tz = pytz.timezone(TIMEZONE)
    lines = []
    current_day = None

    for event in events:
        start_raw = event["start"].get("dateTime", event["start"].get("date"))
        end_raw = event["end"].get("dateTime", event["end"].get("date"))
        summary = event.get("summary", "Sem título")
        event_id = event.get("id", "")

        if "T" in start_raw:
            start_dt = datetime.fromisoformat(start_raw.replace("Z", "+00:00")).astimezone(tz)
            end_dt = datetime.fromisoformat(end_raw.replace("Z", "+00:00")).astimezone(tz)
            day_label = start_dt.strftime("%A, %d/%m")
            time_str = f"{start_dt.strftime('%H:%M')}–{end_dt.strftime('%H:%M')}"
        else:
            start_dt = datetime.strptime(start_raw, "%Y-%m-%d")
            day_label = start_dt.strftime("%A, %d/%m")
            time_str = "dia todo"

        if day_label != current_day:
            lines.append(f"\n{day_label}:")
            current_day = day_label

        desc = event.get("description", "")
        desc_str = f" — {desc[:80]}" if desc else ""
        lines.append(f"  • {time_str} {summary}{desc_str} [id:{event_id[:8]}]")

    return "\n".join(lines)
