"""Google Meet + Calendar via raw HTTP (httpx). No google-api-python-client dep.

Per-user OAuth: you supply the app ``client_id``/``client_secret`` and manage the
user's tokens yourself (a DB row, a file, env vars — the library does not care).
Every call takes a raw access ``token``; refresh it with :func:`refresh_token`
when it nears expiry, or let :class:`MeetClient` do it via a ``token_provider``.

Extracted from the Vendox HR interview scheduler (Meet room creation + cloud
recording pull). Only dependency is ``httpx``.

Quick use:
    from vdx_auto_utils import google_meet as gm

    # 1. one-time: send user through OAuth consent
    url = gm.build_auth_url(CLIENT_ID, "https://app/callback")
    # ... user consents, you receive ?code=...
    tok = gm.exchange_code(CLIENT_ID, CLIENT_SECRET, code, "https://app/callback")
    access, refresh = tok["access_token"], tok["refresh_token"]

    # 2. open a Meet room
    meet = gm.create_meet_space(access)
    print(meet["meeting_uri"])   # https://meet.google.com/abc-defg-hij
"""

from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

import httpx

# OAuth scopes needed for the full flow (Meet space, Calendar, recording pull).
SCOPES = [
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/meetings.space.created",
    "https://www.googleapis.com/auth/drive.readonly",
    "openid",
    "email",
]
TOKEN_URL = "https://oauth2.googleapis.com/token"
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"

DEFAULT_TZ = "Asia/Kuala_Lumpur"


def _headers(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _auth_only(token):
    return {"Authorization": f"Bearer {token}"}


# --------------------------------------------------------------------------- #
# OAuth
# --------------------------------------------------------------------------- #


def build_auth_url(
    client_id,
    redirect_uri,
    scopes=None,
    state="",
    access_type="offline",
    prompt="select_account consent",
):
    """Build the Google OAuth consent URL to redirect the user to.

    ``access_type="offline"`` + a consent ``prompt`` are required to get a
    refresh token back. Returns the fully-encoded URL string.
    """
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(scopes or SCOPES),
        "access_type": access_type,
        "prompt": prompt,
        "state": state,
    }
    return f"{AUTH_URL}?{urlencode(params)}"


def exchange_code(client_id, client_secret, code, redirect_uri):
    """Exchange an OAuth ``code`` for tokens. Returns the token dict
    (``access_token``, ``refresh_token``, ``expires_in``, ...)."""
    r = httpx.post(
        TOKEN_URL,
        data={
            "client_id": client_id,
            "client_secret": client_secret,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": redirect_uri,
        },
        timeout=20,
        trust_env=False,
    )
    r.raise_for_status()
    return r.json()


def refresh_token(client_id, client_secret, refresh_token):
    """Refresh an access token. Returns the token dict (no new refresh_token —
    Google reuses the existing one). Raises on HTTP error."""
    r = httpx.post(
        TOKEN_URL,
        data={
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        },
        timeout=20,
        trust_env=False,
    )
    r.raise_for_status()
    return r.json()


def account_email(token):
    """Return the Google account email for a token, or "" on failure."""
    try:
        r = httpx.get(
            "https://www.googleapis.com/oauth2/v2/userinfo",
            headers=_auth_only(token),
            timeout=15,
            trust_env=False,
        )
        if r.is_success:
            return r.json().get("email", "")
    except Exception:
        pass
    return ""


# --------------------------------------------------------------------------- #
# Meet
# --------------------------------------------------------------------------- #


def create_meet_space(token, access_type="TRUSTED", entry_point="ALL"):
    """Create a Meet space (the "open a Meet room" call).

    Args:
        token: A valid access token with the ``meetings.space.created`` scope.
        access_type: Meet access policy — ``"TRUSTED"``, ``"OPEN"`` or ``"RESTRICTED"``.
        entry_point: ``entryPointAccess`` — ``"ALL"`` or ``"CREATOR_APP_ONLY"``.

    Returns:
        dict: ``{"space_name", "meeting_uri", "meeting_code"}``. ``space_name``
        (``"spaces/<id>"``) is the resource name — keep it to fetch the recording
        later via :func:`find_meet_recording`. ``meeting_uri`` is the join link.
    """
    r = httpx.post(
        "https://meet.googleapis.com/v2/spaces",
        headers=_headers(token),
        json={"config": {"accessType": access_type, "entryPointAccess": entry_point}},
        timeout=20,
        trust_env=False,
    )
    r.raise_for_status()
    d = r.json()
    return {
        "space_name": d.get("name", ""),
        "meeting_uri": d.get("meetingUri", ""),
        "meeting_code": d.get("meetingCode", ""),
    }


def find_meet_recording(token, space_name):
    """Find the cloud recording for a Meet space (a ``"spaces/<id>"`` name).

    Walks conferenceRecords for the space -> their recordings -> the Drive file
    id. Returns ``{"file_id", "conference_record", "recording"}`` for the newest
    finished recording, or ``None`` if the space has no finished recording yet.
    """
    if not space_name:
        return None
    # 1) Conference records for this space (a space can be reused across calls).
    r = httpx.get(
        "https://meet.googleapis.com/v2/conferenceRecords",
        headers=_headers(token),
        params={"filter": f'space.name="{space_name}"'},
        timeout=20,
        trust_env=False,
    )
    r.raise_for_status()
    records = r.json().get("conferenceRecords", [])
    # Newest first (endTime desc); Google returns latest-first but sort defensively.
    records.sort(
        key=lambda c: c.get("endTime") or c.get("startTime") or "", reverse=True
    )

    for rec in records:
        rec_name = rec.get("name")
        if not rec_name:
            continue
        rr = httpx.get(
            f"https://meet.googleapis.com/v2/{rec_name}/recordings",
            headers=_headers(token),
            timeout=20,
            trust_env=False,
        )
        if not rr.is_success:
            continue
        recordings = rr.json().get("recordings", [])
        for rcd in recordings:
            file_id = (rcd.get("driveDestination") or {}).get("file")
            # FILE_GENERATED means the Drive file is ready; if absent, accept any with a file.
            if file_id and rcd.get("state", "FILE_GENERATED") in (
                "FILE_GENERATED",
                "ENDED",
                "",
            ):
                return {
                    "file_id": file_id,
                    "conference_record": rec_name,
                    "recording": rcd.get("name", ""),
                }
    return None


def download_drive_file(token, file_id):
    """Download a Drive file's bytes (needs the ``drive.readonly`` scope)."""
    r = httpx.get(
        f"https://www.googleapis.com/drive/v3/files/{file_id}",
        headers=_auth_only(token),
        params={"alt": "media"},
        timeout=120,
        trust_env=False,
    )
    r.raise_for_status()
    return r.content


# --------------------------------------------------------------------------- #
# Calendar (compose with Meet for interview scheduling)
# --------------------------------------------------------------------------- #


def create_event(
    token,
    summary,
    date,
    start_time,
    duration_minutes,
    description="",
    attendee_emails=None,
    location="",
    tz=DEFAULT_TZ,
):
    """Create a Calendar event on the user's primary calendar and email invites.

    Args:
        date: ``"YYYY-MM-DD"``. start_time: ``"HH:MM"`` (24h, in ``tz``).
        location: put the Meet ``meeting_uri`` here to attach the join link.
        attendee_emails: list of emails (deduped; ``sendUpdates=all``).

    Returns the created event dict (``id``, ``htmlLink``, ...).
    """
    zone = ZoneInfo(tz)
    start = datetime.strptime(f"{date} {start_time}", "%Y-%m-%d %H:%M").replace(
        tzinfo=zone
    )
    end = start + timedelta(minutes=duration_minutes)
    attendees = [
        {"email": e} for e in dict.fromkeys(filter(None, attendee_emails or []))
    ]
    body = {
        "summary": summary,
        "description": description,
        "start": {"dateTime": start.isoformat(), "timeZone": tz},
        "end": {"dateTime": end.isoformat(), "timeZone": tz},
    }
    if location:
        body["location"] = location
    if attendees:
        body["attendees"] = attendees
    r = httpx.post(
        "https://www.googleapis.com/calendar/v3/calendars/primary/events?sendUpdates=all",
        headers=_headers(token),
        json=body,
        timeout=20,
        trust_env=False,
    )
    r.raise_for_status()
    return r.json()


def get_free_slots(
    token,
    start_date,
    end_date,
    duration_minutes=60,
    work_start=9,
    work_end=18,
    tz=DEFAULT_TZ,
):
    """Return open weekday slots in the work window over a date range.

    Queries the primary calendar's free/busy and slices the working hours into
    ``duration_minutes`` slots, skipping busy overlaps and past times.

    Returns ``[{"date", "start_time", "duration_minutes"}]`` (Mon-Fri only).
    """
    zone = ZoneInfo(tz)
    start = datetime.strptime(start_date, "%Y-%m-%d").replace(tzinfo=zone)
    end = datetime.strptime(end_date, "%Y-%m-%d").replace(
        hour=23, minute=59, tzinfo=zone
    )
    body = {
        "timeMin": start.isoformat(),
        "timeMax": end.isoformat(),
        "timeZone": tz,
        "items": [{"id": "primary"}],
    }
    r = httpx.post(
        "https://www.googleapis.com/calendar/v3/freeBusy",
        headers=_headers(token),
        json=body,
        timeout=20,
        trust_env=False,
    )
    r.raise_for_status()
    busy = []
    for b in r.json().get("calendars", {}).get("primary", {}).get("busy", []):
        busy.append(
            (
                datetime.fromisoformat(b["start"].replace("Z", "+00:00")).astimezone(
                    zone
                ),
                datetime.fromisoformat(b["end"].replace("Z", "+00:00")).astimezone(
                    zone
                ),
            )
        )

    slots = []
    day = start.replace(hour=0, minute=0, second=0, microsecond=0)
    last = end.replace(hour=0, minute=0, second=0, microsecond=0)
    now = datetime.now(timezone.utc).astimezone(zone)
    while day <= last:
        if day.weekday() < 5:  # Mon-Fri
            t = day.replace(hour=work_start)
            day_end = day.replace(hour=work_end)
            while t + timedelta(minutes=duration_minutes) <= day_end:
                s_end = t + timedelta(minutes=duration_minutes)
                overlaps = any(t < be and bs < s_end for bs, be in busy)
                if not overlaps and t > now:
                    slots.append(
                        {
                            "date": t.strftime("%Y-%m-%d"),
                            "start_time": t.strftime("%H:%M"),
                            "duration_minutes": duration_minutes,
                        }
                    )
                t = s_end
        day += timedelta(days=1)
    return slots


# --------------------------------------------------------------------------- #
# Convenience client — bind app credentials + a token source once
# --------------------------------------------------------------------------- #


class MeetClient:
    """Bind app credentials and a token source so calls don't repeat plumbing.

    Args:
        client_id, client_secret: your Google app OAuth credentials.
        token: a raw access token to use directly (simplest).
        token_provider: OR a zero-arg callable returning a fresh access token
            (e.g. reads your DB row and refreshes). Called on every request, so
            it should return an already-valid token.
        tz: default timezone for Calendar helpers.

    Provide exactly one of ``token`` / ``token_provider``.
    """

    def __init__(
        self, client_id, client_secret, token=None, token_provider=None, tz=DEFAULT_TZ
    ):
        if bool(token) == bool(token_provider):
            raise ValueError("Provide exactly one of `token` or `token_provider`.")
        self.client_id = client_id
        self.client_secret = client_secret
        self._token = token
        self._token_provider = token_provider
        self.tz = tz

    def _tok(self):
        return self._token_provider() if self._token_provider else self._token

    # OAuth (bound credentials)
    def auth_url(self, redirect_uri, scopes=None, state=""):
        return build_auth_url(self.client_id, redirect_uri, scopes=scopes, state=state)

    def exchange(self, code, redirect_uri):
        return exchange_code(self.client_id, self.client_secret, code, redirect_uri)

    def refresh(self, refresh_tok):
        return refresh_token(self.client_id, self.client_secret, refresh_tok)

    def email(self):
        return account_email(self._tok())

    # Meet
    def create_space(self, access_type="TRUSTED", entry_point="ALL"):
        return create_meet_space(self._tok(), access_type, entry_point)

    def find_recording(self, space_name):
        return find_meet_recording(self._tok(), space_name)

    def download_file(self, file_id):
        return download_drive_file(self._tok(), file_id)

    # Calendar
    def create_event(self, summary, date, start_time, duration_minutes, **kw):
        kw.setdefault("tz", self.tz)
        return create_event(
            self._tok(), summary, date, start_time, duration_minutes, **kw
        )

    def free_slots(self, start_date, end_date, **kw):
        kw.setdefault("tz", self.tz)
        return get_free_slots(self._tok(), start_date, end_date, **kw)
