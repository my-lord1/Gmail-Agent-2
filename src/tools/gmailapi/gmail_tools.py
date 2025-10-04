"""
Gmail tools implementation module for LangChain agents.
Requires Gmail API credentials and proper authentication.
"""

import os
import base64
import json
import logging
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any, Iterator
from pathlib import Path
from pydantic import Field, BaseModel
from langchain_core.tools import tool

from googleapiclient.discovery import build
from email.mime.text import MIMEText
from dateutil.parser import parse as parse_time
from google.oauth2.credentials import Credentials

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Define paths for credentials
_ROOT = Path(__file__).parent.absolute()
_SECRETS_DIR = _ROOT / ".secrets"


def extract_message_part(payload: Dict[str, Any]) -> str:
    """
    Recursively extract text content from email payload.
    Handles both simple and multipart MIME messages.
    """
    if payload.get("body", {}).get("data"):
        data = payload["body"]["data"]
        decoded = base64.urlsafe_b64decode(data).decode("utf-8")
        return decoded
        
    if payload.get("parts"):
        text_parts = []
        for part in payload["parts"]:
            content = extract_message_part(part)
            if content:
                text_parts.append(content)
        return "\n".join(text_parts)
        
    return ""


def get_credentials(gmail_token: Optional[str] = None, gmail_secret: Optional[str] = None) -> Credentials:
    """
    Load Gmail API credentials from token data.
    
    Priority order:
    1. Directly passed gmail_token parameter
    2. GMAIL_TOKEN environment variable
    3. Local token.json file in .secrets directory
    
    Args:
        gmail_token: Optional JSON string containing token data
        gmail_secret: Optional credentials (reserved for future use)
        
    Returns:
        Google OAuth2 Credentials object
        
    Raises:
        ValueError: If no valid credentials can be loaded
    """
    token_path = _SECRETS_DIR / "token.json"
    token_data = None
    
    # Try directly passed token parameter
    if gmail_token:
        try:
            token_data = json.loads(gmail_token) if isinstance(gmail_token, str) else gmail_token
            logger.info("Using directly provided gmail_token parameter")
        except json.JSONDecodeError as e:
            logger.warning(f"Could not parse provided gmail_token: {str(e)}")
    
    # Try environment variable
    if token_data is None:
        env_token = os.getenv("GMAIL_TOKEN")
        if env_token:
            try:
                token_data = json.loads(env_token)
                logger.info("Using GMAIL_TOKEN environment variable")
            except json.JSONDecodeError as e:
                logger.warning(f"Could not parse GMAIL_TOKEN environment variable: {str(e)}")
    
    # Try local file
    if token_data is None and token_path.exists():
        try:
            with open(token_path, "r") as f:
                token_data = json.load(f)
            logger.info(f"Using token from {token_path}")
        except Exception as e:
            logger.warning(f"Could not load token from {token_path}: {str(e)}")
    
    # Raise error if no credentials found
    if token_data is None:
        raise ValueError(
            "No Gmail credentials found. Please provide credentials via:\n"
            "1. gmail_token parameter\n"
            "2. GMAIL_TOKEN environment variable\n"
            "3. .secrets/token.json file"
        )
    
    # Create and return credentials object
    credentials = Credentials(
        token=token_data.get("token"),
        refresh_token=token_data.get("refresh_token"),
        token_uri=token_data.get("token_uri", "https://oauth2.googleapis.com/token"),
        client_id=token_data.get("client_id"),
        client_secret=token_data.get("client_secret"),
        scopes=token_data.get("scopes", ["https://www.googleapis.com/auth/gmail.modify"])
    )
    
    return credentials


def fetch_group_emails(
    email_address: str,
    minutes_since: int = 30,
    gmail_token: Optional[str] = None,
    gmail_secret: Optional[str] = None,
    include_read: bool = False,
    skip_filters: bool = False,
) -> Iterator[Dict[str, Any]]:
    """
    Fetch recent emails from Gmail involving the specified email address.
    
    This function retrieves emails where the specified address is either sender
    or recipient, with intelligent filtering to avoid duplicate responses.
    
    Args:
        email_address: Email address to fetch messages for
        minutes_since: Only retrieve emails newer than this many minutes
        gmail_token: Optional token for Gmail API authentication
        gmail_secret: Optional credentials for Gmail API authentication
        include_read: Include already-read emails (default: False)
        skip_filters: Skip thread/sender filtering, return all messages (default: False)
        
    Yields:
        Dict objects containing processed email information:
        - from_email: Sender's email address
        - to_email: Recipient's email address
        - subject: Email subject line
        - page_content: Email body text
        - id: Gmail message ID
        - thread_id: Gmail thread ID
        - send_time: ISO format timestamp
        - user_respond: True if user already replied (only when skip_filters=False)
        
    Raises:
        ValueError: If credentials cannot be loaded
        Exception: For Gmail API errors
    """
    # Get Gmail API credentials
    creds = get_credentials(gmail_token, gmail_secret)
    service = build("gmail", "v1", credentials=creds)
    
    # Calculate timestamp for filtering
    after = int((datetime.now() - timedelta(minutes=minutes_since)).timestamp())
    
    # Construct Gmail search query
    query = f"(to:{email_address} OR from:{email_address}) after:{after}"
    
    if not include_read:
        query += " is:unread"
    
    logger.info(f"Gmail search query: {query}")
    
    # Retrieve all matching messages (with pagination)
    messages = []
    next_page_token = None
    
    while True:
        results = service.users().messages().list(
            userId="me", 
            q=query, 
            pageToken=next_page_token
        ).execute()
        
        if "messages" in results:
            new_messages = results["messages"]
            messages.extend(new_messages)
            logger.info(f"Found {len(new_messages)} messages in this page")
        
        next_page_token = results.get("nextPageToken")
        if not next_page_token:
            break
    
    logger.info(f"Total messages found: {len(messages)}")
    
    # Process each message
    processed_count = 0
    
    for message in messages:
        try:
            # Get full message details
            msg = service.users().messages().get(userId="me", id=message["id"]).execute()
            thread_id = msg["threadId"]
            payload = msg["payload"]
            headers = payload.get("headers", [])
            
            # Get thread context to understand conversation flow
            thread = service.users().threads().get(userId="me", id=thread_id).execute()
            messages_in_thread = thread["messages"]
            
            # Sort messages chronologically
            if all("internalDate" in m for m in messages_in_thread):
                messages_in_thread.sort(key=lambda m: int(m.get("internalDate", 0)))
            else:
                messages_in_thread.sort(key=lambda m: m["id"])
            
            logger.debug(f"Thread {thread_id} has {len(messages_in_thread)} messages")
            
            # Analyze last message in thread
            last_message = messages_in_thread[-1]
            last_headers = last_message["payload"]["headers"]
            last_from = next(h["value"] for h in last_headers if h["name"] == "From")
            
            # Check if user already responded
            if not skip_filters and email_address in last_from:
                yield {
                    "id": message["id"],
                    "thread_id": thread_id,
                    "user_respond": True,
                }
                logger.debug(f"Skipping {message['id']}: user already responded")
                continue
            
            # Determine if message should be processed
            from_header = next(h["value"] for h in headers if h["name"] == "From")
            is_from_user = email_address in from_header
            is_latest_in_thread = message["id"] == last_message["id"]
            
            # Apply filtering logic
            should_process = skip_filters or (not is_from_user and is_latest_in_thread)
            
            if not should_process:
                logger.debug(
                    f"Skipping {message['id']}: "
                    f"from_user={is_from_user}, latest={is_latest_in_thread}"
                )
                continue
            
            # Use appropriate message based on filtering
            process_message = last_message if skip_filters else message
            process_payload = process_message["payload"] if skip_filters else payload
            process_headers = process_payload.get("headers", [])
            
            # Extract email metadata
            subject = next(h["value"] for h in process_headers if h["name"] == "Subject")
            from_email = next((h["value"] for h in process_headers if h["name"] == "From"), "")
            to_email = next((h["value"] for h in process_headers if h["name"] == "To"), "")
            
            # Use Reply-To if present (for mailing lists, etc.)
            if reply_to := next((h["value"] for h in process_headers if h["name"] == "Reply-To"), ""):
                from_email = reply_to
            
            # Parse send time
            send_time = next(h["value"] for h in process_headers if h["name"] == "Date")
            parsed_time = parse_time(send_time)
            
            # Extract email body
            body = extract_message_part(process_payload)
            
            # Yield processed email data
            yield {
                "from_email": from_email.strip(),
                "to_email": to_email.strip(),
                "subject": subject,
                "page_content": body,
                "id": process_message["id"],
                "thread_id": process_message["threadId"],
                "send_time": parsed_time.isoformat(),
            }
            processed_count += 1
            
        except Exception as e:
            logger.warning(f"Failed to process message {message['id']}: {str(e)}")
    
    logger.info(f"Processed {processed_count} emails out of {len(messages)} total messages")


def send_email(
    email_id: str,
    response_text: str,
    email_address: str,
    addn_recipients: Optional[List[str]] = None,
    gmail_token: Optional[str] = None,
    gmail_secret: Optional[str] = None,
) -> bool:
    """
    Send a reply to an existing email thread.
    
    Args:
        email_id: Gmail message ID to reply to
        response_text: Content of the reply
        email_address: Sender's email address (current user)
        addn_recipients: Optional additional CC recipients
        gmail_token: Optional token for authentication
        gmail_secret: Optional credentials for authentication
        
    Returns:
        True if email was sent successfully
        
    Raises:
        ValueError: If credentials cannot be loaded or original message not found
        Exception: For Gmail API errors
    """
    creds = get_credentials(gmail_token, gmail_secret)
    service = build("gmail", "v1", credentials=creds)
    
    # Get original message to extract reply context
    try:
        message = service.users().messages().get(userId="me", id=email_id).execute()
        headers = message["payload"]["headers"]
        
        # Extract subject and add Re: prefix if needed
        subject = next(h["value"] for h in headers if h["name"] == "Subject")
        if not subject.startswith("Re:"):
            subject = f"Re: {subject}"
        
        # Get original sender
        original_from = next(h["value"] for h in headers if h["name"] == "From")
        thread_id = message["threadId"]
        
    except Exception as e:
        raise ValueError(f"Could not retrieve original message {email_id}: {str(e)}")
    
    # Create reply message
    msg = MIMEText(response_text)
    msg["to"] = original_from
    msg["from"] = email_address
    msg["subject"] = subject
    
    if addn_recipients:
        msg["cc"] = ", ".join(addn_recipients)
    
    # Encode and send
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("utf-8")
    body = {"raw": raw, "threadId": thread_id}
    
    sent_message = service.users().messages().send(userId="me", body=body).execute()
    logger.info(f"Email sent successfully: Message ID {sent_message['id']}")
    
    return True


def get_calendar_events(
    dates: List[str],
    gmail_token: Optional[str] = None,
    gmail_secret: Optional[str] = None,
) -> str:
    """
    Check Google Calendar for events on specified dates.
    
    Args:
        dates: List of dates in DD-MM-YYYY format
        gmail_token: Optional token for authentication
        gmail_secret: Optional credentials for authentication
        
    Returns:
        Formatted string with calendar events and availability
        
    Raises:
        ValueError: If credentials cannot be loaded
        Exception: For Calendar API errors
    """
    creds = get_credentials(gmail_token, gmail_secret)
    service = build("calendar", "v3", credentials=creds)
    
    result = "Calendar events:\n\n"
    
    for date_str in dates:
        day, month, year = date_str.split("-")
        start_time = f"{year}-{month}-{day}T00:00:00Z"
        end_time = f"{year}-{month}-{day}T23:59:59Z"
        
        # Fetch events for the day
        events_result = service.events().list(
            calendarId="primary",
            timeMin=start_time,
            timeMax=end_time,
            singleEvents=True,
            orderBy="startTime",
        ).execute()
        
        events = events_result.get("items", [])
        result += f"Events for {date_str}:\n"
        
        if not events:
            result += "  No events found\n"
            result += "  Available all day\n\n"
            continue
        
        # Process each event
        busy_slots = []
        for event in events:
            start = event["start"].get("dateTime", event["start"].get("date"))
            end = event["end"].get("dateTime", event["end"].get("date"))
            
            if "T" in start:  # Timed event
                start_dt = datetime.fromisoformat(start.replace("Z", "+00:00"))
                end_dt = datetime.fromisoformat(end.replace("Z", "+00:00"))
                start_display = start_dt.strftime("%I:%M %p")
                end_display = end_dt.strftime("%I:%M %p")
                result += f"  - {start_display} - {end_display}: {event['summary']}\n"
                busy_slots.append((start_dt, end_dt))
            else:  # All-day event
                result += f"  - All day: {event['summary']}\n"
                busy_slots.append(("all-day", "all-day"))
        
        # Calculate available time slots
        if "all-day" in [slot[0] for slot in busy_slots]:
            result += "  Available: None (all-day events)\n\n"
        else:
            busy_slots.sort(key=lambda x: x[0])
            
            # Define working hours (9 AM - 5 PM)
            work_start = datetime(int(year), int(month), int(day), 9, 0)
            work_end = datetime(int(year), int(month), int(day), 17, 0)
            
            # Find gaps between busy slots
            available_slots = []
            current = work_start
            
            for start, end in busy_slots:
                if current < start:
                    available_slots.append((current, start))
                current = max(current, end)
            
            if current < work_end:
                available_slots.append((current, work_end))
            
            # Format availability
            if available_slots:
                result += "  Available: "
                for i, (start, end) in enumerate(available_slots):
                    result += f"{start.strftime('%I:%M %p')} - {end.strftime('%I:%M %p')}"
                    if i < len(available_slots) - 1:
                        result += ", "
                result += "\n\n"
            else:
                result += "  Available: None during working hours\n\n"
    
    return result


def send_calendar_invite(
    attendees: List[str],
    title: str,
    start_time: str,
    end_time: str,
    organizer_email: str,
    timezone: str = "America/Los_Angeles",
    gmail_token: Optional[str] = None,
    gmail_secret: Optional[str] = None,
) -> bool:
    """
    Schedule a meeting with Google Calendar and send invites.
    
    Args:
        attendees: Email addresses of attendees
        title: Meeting title/subject
        start_time: ISO format start time (YYYY-MM-DDTHH:MM:SS)
        end_time: ISO format end time (YYYY-MM-DDTHH:MM:SS)
        organizer_email: Organizer's email address
        timezone: Timezone for the meeting
        gmail_token: Optional token for authentication
        gmail_secret: Optional credentials for authentication
        
    Returns:
        True if meeting was scheduled successfully
        
    Raises:
        ValueError: If credentials cannot be loaded
        Exception: For Calendar API errors
    """
    creds = get_credentials(gmail_token, gmail_secret)
    service = build("calendar", "v3", credentials=creds)
    
    # Create event
    event = {
        "summary": title,
        "start": {"dateTime": start_time, "timeZone": timezone},
        "end": {"dateTime": end_time, "timeZone": timezone},
        "attendees": [{"email": email} for email in attendees],
        "organizer": {"email": organizer_email, "self": True},
        "reminders": {"useDefault": True},
        "sendUpdates": "all",  # Send email notifications
    }
    
    # Insert event
    created_event = service.events().insert(calendarId="primary", body=event).execute()
    logger.info(f"Meeting created: {created_event.get('htmlLink')}")
    
    return True


def mark_as_read(
    message_id: str,
    gmail_token: Optional[str] = None,
    gmail_secret: Optional[str] = None,
) -> bool:
    """
    Mark a Gmail message as read.
    
    Args:
        message_id: Gmail message ID to mark as read
        gmail_token: Optional token for authentication
        gmail_secret: Optional credentials for authentication
        
    Returns:
        True if successfully marked as read
        
    Raises:
        ValueError: If credentials cannot be loaded
        Exception: For Gmail API errors
    """
    creds = get_credentials(gmail_token, gmail_secret)
    service = build("gmail", "v1", credentials=creds)
    
    service.users().messages().modify(
        userId="me",
        id=message_id,
        body={"removeLabelIds": ["UNREAD"]}
    ).execute()
    
    logger.info(f"Marked message {message_id} as read")
    return True


# ============================================================================
# LANGCHAIN TOOLS
# ============================================================================

class FetchEmailsInput(BaseModel):
    """Input schema for fetch_emails_tool."""
    email_address: str = Field(description="Email address to fetch emails for")
    minutes_since: int = Field(default=30, description="Only retrieve emails newer than this many minutes")
    include_read: bool = Field(default=False, description="Include already-read emails")


@tool(args_schema=FetchEmailsInput)
def fetch_emails_tool(
    email_address: str,
    minutes_since: int = 30,
    include_read: bool = False
) -> str:
    """
    Fetch recent emails from Gmail for the specified email address.
    Returns a formatted summary of unread (or all) emails.
    """
    try:
        emails = list(fetch_group_emails(
            email_address=email_address,
            minutes_since=minutes_since,
            include_read=include_read
        ))
        
        if not emails:
            return "No new emails found."
        
        result = f"Found {len(emails)} emails:\n\n"
        
        for i, email in enumerate(emails, 1):
            if email.get("user_respond", False):
                result += f"{i}. Already responded (Thread: {email['thread_id']})\n\n"
                continue
            
            result += f"{i}. From: {email['from_email']}\n"
            result += f"   To: {email['to_email']}\n"
            result += f"   Subject: {email['subject']}\n"
            result += f"   Time: {email['send_time']}\n"
            result += f"   ID: {email['id']}\n"
            result += f"   Thread: {email['thread_id']}\n"
            result += f"   Content: {email['page_content'][:200]}...\n\n"
        
        return result
        
    except Exception as e:
        logger.error(f"Error fetching emails: {str(e)}")
        return f"Failed to fetch emails: {str(e)}"


class SendEmailInput(BaseModel):
    """Input schema for send_email_tool."""
    email_id: str = Field(description="Gmail message ID to reply to")
    response_text: str = Field(description="Content of the reply")
    email_address: str = Field(description="Your email address (sender)")
    additional_recipients: Optional[List[str]] = Field(default=None, description="Additional CC recipients")


@tool(args_schema=SendEmailInput)
def send_email_tool(
    email_id: str,
    response_text: str,
    email_address: str,
    additional_recipients: Optional[List[str]] = None
) -> str:
    """
    Send a reply to an existing email thread in Gmail.
    """
    try:
        success = send_email(
            email_id=email_id,
            response_text=response_text,
            email_address=email_address,
            addn_recipients=additional_recipients
        )
        
        if success:
            return f"Email reply sent successfully to message ID: {email_id}"
        else:
            return "Failed to send email"
            
    except Exception as e:
        logger.error(f"Error sending email: {str(e)}")
        return f"Failed to send email: {str(e)}"


class CheckCalendarInput(BaseModel):
    """Input schema for check_calendar_tool."""
    dates: List[str] = Field(description="List of dates to check in DD-MM-YYYY format")


@tool(args_schema=CheckCalendarInput)
def check_calendar_tool(dates: List[str]) -> str:
    """
    Check Google Calendar for events on specified dates.
    Returns formatted events and available time slots.
    """
    try:
        return get_calendar_events(dates)
    except Exception as e:
        logger.error(f"Error checking calendar: {str(e)}")
        return f"Failed to check calendar: {str(e)}"


class ScheduleMeetingInput(BaseModel):
    """Input schema for schedule_meeting_tool."""
    attendees: List[str] = Field(description="Email addresses of meeting attendees")
    title: str = Field(description="Meeting title/subject")
    start_time: str = Field(description="Meeting start time (YYYY-MM-DDTHH:MM:SS)")
    end_time: str = Field(description="Meeting end time (YYYY-MM-DDTHH:MM:SS)")
    organizer_email: str = Field(description="Organizer's email address")
    timezone: str = Field(default="America/Los_Angeles", description="Timezone")


@tool(args_schema=ScheduleMeetingInput)
def schedule_meeting_tool(
    attendees: List[str],
    title: str,
    start_time: str,
    end_time: str,
    organizer_email: str,
    timezone: str = "America/Los_Angeles"
) -> str:
    """
    Schedule a meeting with Google Calendar and send invites to attendees.
    """
    try:
        success = send_calendar_invite(
            attendees=attendees,
            title=title,
            start_time=start_time,
            end_time=end_time,
            organizer_email=organizer_email,
            timezone=timezone
        )
        
        if success:
            return f"Meeting '{title}' scheduled successfully from {start_time} to {end_time}"
        else:
            return "Failed to schedule meeting"
            
    except Exception as e:
        logger.error(f"Error scheduling meeting: {str(e)}")
        return f"Failed to schedule meeting: {str(e)}"