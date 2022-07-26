from typing import Tuple, Dict, List
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from google.auth.transport.requests import Request

import json
import engine.sqlite.database as db
import engine.global_params as global_params

# Google Calendar write access
SCOPES = ["https://www.googleapis.com/auth/calendar"]

# Dict keys for passing data between processes
STATE_KEY = "state"
CREDENTIALS_KEY = "credentials"

# Google Calendar API consts
SERVICE = "calendar"
VERSION = "v3"

# Google Calendar API access types
FREE_BUSY_READER = "freeBusyReader"
READER = "reader"
WRITER = "writer"


def get_authz_link() -> Tuple[str, str]:
    """
        Generate OAuth2.0 authorization link with write access to Google Calendar API

        :return: OAuth2.0 authorization URL, state string (helps map callback response to original request)
    """
    flow = Flow.from_client_secrets_file(global_params.CLIENT_SECRET, scopes=SCOPES)
    flow.redirect_uri = global_params.REDIRECT_URL
    return flow.authorization_url(access_type='offline', include_granted_scopes='true', prompt="consent")


def get_authz_token(callback_url: str, state: str) -> str:
    """
        Exchange authorization grant token for credentials

        :param: callback_url: full URL requested, including parameters
        :param: state: string, received from get_authz_link, maps original authorization request and received callback

        :return: string, Google API credentials as JSON
    """
    flow = Flow.from_client_secrets_file(global_params.CLIENT_SECRET, scopes=SCOPES, state=state)
    flow.redirect_uri = global_params.REDIRECT_URL
    flow.fetch_token(authorization_response=callback_url)
    return flow.credentials.to_json()


def get_calendars(creds: Credentials) -> List[str]:
    """
        Retrieve available calendars

        :param: creds: Google API credentials

        :return: list of calendar names
    """
    service = build(serviceName=SERVICE, version=VERSION, credentials=creds)
    calendars_raw = service.calendarList().list().execute()
    # List calendars, owned by user, not shared with him
    calendars = [cal["id"] for cal in calendars_raw["items"] if cal["accessRole"] == "owner"]

    return calendars


def get_acl_users(creds: Credentials, calendar: str) -> List[Dict]:
    """
        Retrieve users, who have access to specified calendar

        :param: creds: Google API credentials
        :param: calendar: Google Calendar name

        :return: list of users as dictionary in format {"name": user email, "role": Google access role}
    """
    service = build(serviceName=SERVICE, version=VERSION, credentials=creds)
    users_acl = service.acl().list(calendarId=calendar).execute()
    users = [{"name": user["scope"]["value"], "role": user["role"]} for user in users_acl["items"]
             if user["role"] != "owner"]
    return users


def delete_acl_user(creds: Credentials, calendar: str, username: str) -> None:
    """
        Revoke user access to the specified calendar

        :param: creds: Google API credentials
        :param: calendar: Google Calendar name
        :param: username: user e-mail that has access to calendar
    """
    service = build(serviceName=SERVICE, version=VERSION, credentials=creds)
    users_acl = service.acl().list(calendarId=calendar).execute()
    users = [user["id"] for user in users_acl["items"] if user["scope"]["value"] == username]
    for user in users:
        service.acl().delete(calendarId=calendar, ruleId=user).execute()


def add_acl_user(creds: Credentials, calendar: str, username: str, access_type: str) -> None:
    """
        Add user access to the specified calendar

        :param: creds: Google API credentials
        :param: calendar: Google Calendar name
        :param: username: user e-mail that has access to calendar
        :param: access_type: Google Calendar access role: freeBusyReader, reader, writer
    """
    service = build(serviceName=SERVICE, version=VERSION, credentials=creds)
    rule = {
        'scope': {
            'type': "user",
            'value': f"{username}"
        },
        'role': f"{access_type}"
    }
    service.acl().insert(calendarId=calendar, body=rule).execute()


def str_to_credentials(chat_id: int, creds: str) -> Credentials:
    """
        Convert Google API credentials from JSON to an object. Updates database with redreshed token if necessary.

        :param: chat_id: ID of Telegram chat as a key in database
        :param: creds: Google API credentials as JSON string
    """
    js = json.loads(creds)
    creds = Credentials.from_authorized_user_info(js)

    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        db.update_credentials(chat_id, creds.to_json())

    return creds
