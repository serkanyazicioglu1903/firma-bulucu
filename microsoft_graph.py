import json
from datetime import datetime, timedelta, timezone

import msal
import requests

GRAPH_BASE = "https://graph.microsoft.com/v1.0"
DEFAULT_SCOPES = ["User.Read", "Mail.Read", "Calendars.Read"]


def build_cache(serialized_cache=None):
    cache = msal.SerializableTokenCache()
    if serialized_cache:
        try:
            cache.deserialize(serialized_cache)
        except Exception:
            pass
    return cache


def build_app(client_id, tenant_id="organizations", cache=None):
    authority = f"https://login.microsoftonline.com/{tenant_id or 'organizations'}"
    return msal.PublicClientApplication(
        client_id=client_id,
        authority=authority,
        token_cache=cache,
    )


def get_cached_token(client_id, tenant_id="organizations", serialized_cache=None, scopes=None):
    scopes = scopes or DEFAULT_SCOPES
    cache = build_cache(serialized_cache)
    app = build_app(client_id, tenant_id, cache)
    accounts = app.get_accounts()
    if not accounts:
        return None, cache.serialize()
    result = app.acquire_token_silent(scopes, account=accounts[0])
    return result, cache.serialize()


def start_device_flow(client_id, tenant_id="organizations", scopes=None, serialized_cache=None):
    scopes = scopes or DEFAULT_SCOPES
    cache = build_cache(serialized_cache)
    app = build_app(client_id, tenant_id, cache)
    flow = app.initiate_device_flow(scopes=scopes)
    if "user_code" not in flow:
        raise RuntimeError(flow.get("error_description") or "Microsoft device flow başlatılamadı.")
    return flow, cache.serialize()


def finish_device_flow(client_id, tenant_id, flow, scopes=None, serialized_cache=None):
    scopes = scopes or DEFAULT_SCOPES
    cache = build_cache(serialized_cache)
    app = build_app(client_id, tenant_id, cache)
    result = app.acquire_token_by_device_flow(flow)
    return result, cache.serialize()


def graph_get(access_token, path, params=None):
    response = requests.get(
        GRAPH_BASE + path,
        headers={"Authorization": f"Bearer {access_token}"},
        params=params,
        timeout=30,
    )
    response.raise_for_status()
    return response.json()


def get_profile(access_token):
    return graph_get(
        access_token,
        "/me",
        params={"$select": "displayName,mail,userPrincipalName,id"},
    )


def get_recent_messages(access_token, top=50):
    data = graph_get(
        access_token,
        "/me/mailFolders/inbox/messages",
        params={
            "$top": str(int(top)),
            "$orderby": "receivedDateTime desc",
            "$select": (
                "id,conversationId,subject,from,toRecipients,ccRecipients,"
                "receivedDateTime,bodyPreview,webLink,isRead,hasAttachments"
            ),
        },
    )
    return data.get("value", [])


def get_calendar_events(access_token, days_back=1, days_forward=30, top=100):
    now = datetime.now(timezone.utc)
    start = now - timedelta(days=int(days_back))
    end = now + timedelta(days=int(days_forward))
    data = graph_get(
        access_token,
        "/me/calendarView",
        params={
            "startDateTime": start.isoformat(),
            "endDateTime": end.isoformat(),
            "$top": str(int(top)),
            "$orderby": "start/dateTime",
            "$select": (
                "id,subject,start,end,attendees,organizer,webLink,"
                "isOnlineMeeting,onlineMeetingUrl,bodyPreview,location"
            ),
        },
    )
    return data.get("value", [])


def primary_sender(message):
    sender = (message or {}).get("from") or {}
    email = sender.get("emailAddress") or {}
    return {
        "name": email.get("name") or "",
        "address": (email.get("address") or "").lower(),
    }


def attendee_addresses(event):
    result = []
    for item in (event or {}).get("attendees") or []:
        email = (item or {}).get("emailAddress") or {}
        address = (email.get("address") or "").lower()
        if address:
            result.append(address)
    organizer = ((event or {}).get("organizer") or {}).get("emailAddress") or {}
    address = (organizer.get("address") or "").lower()
    if address:
        result.append(address)
    return list(dict.fromkeys(result))
