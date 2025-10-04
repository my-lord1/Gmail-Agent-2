"""Gmail tools for email assistant."""

from src.tools.gmailapi.gmail_tools import (
    fetch_emails_tool,
    send_email_tool,
    check_calendar_tool,
    schedule_meeting_tool
)

from src.tools.gmailapi.prompt_templates import GMAIL_TOOLS_PROMPT

__all__ = [
    "fetch_emails_tool",
    "send_email_tool",
    "check_calendar_tool",
    "schedule_meeting_tool",
    "GMAIL_TOOLS_PROMPT"
]