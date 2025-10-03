#parse_gmail, format_for_display, format_gmail_markdown
from typing import List, Any
import json
import html2text

def format_gmail_markdown(subject, author, to, email_thread, email_id=None):
    """Format Gmail email details into a nicely formatted markdown string for display,
    with HTML to text conversion for HTML content
    
    Args:
        subject: Email subject
        author: Email sender
        to: Email recipient
        email_thread: Email content (possibly HTML)
        email_id: Optional email ID (for Gmail API)
    """
    id_section = f"\n**ID**: {email_id}" if email_id else ""
    
    # Check if email_thread is HTML content and convert to text if needed
    if email_thread and (email_thread.strip().startswith("<!DOCTYPE") or 
                          email_thread.strip().startswith("<html") or
                          "<body" in email_thread):
        # Convert HTML to markdown text
        h = html2text.HTML2Text()
        h.ignore_links = False
        h.ignore_images = True
        h.body_width = 0  # Don't wrap text
        email_thread = h.handle(email_thread)
    
    return f"""
        **Subject**: {subject}
        **From**: {author}
        **To**: {to}{id_section}
        {email_thread}
        ---
    """

def format_for_display(tool_call):
    """Format content for display in Agent Inbox
    
    Args:
        tool_call: The tool call to format
    """
    # Initialize empty display
    display = ""
    
    # Add tool call information
    if tool_call["name"] == "write_email":
        display += f"""# Email Draft
        **To**: {tool_call["args"].get("to")}
        **Subject**: {tool_call["args"].get("subject")}

        {tool_call["args"].get("content")}
        """
    elif tool_call["name"] == "schedule_meeting":
        display += f"""# Calendar Invite
        **Meeting**: {tool_call["args"].get("subject")}
        **Attendees**: {', '.join(tool_call["args"].get("attendees"))}
        **Duration**: {tool_call["args"].get("duration_minutes")} minutes
        **Day**: {tool_call["args"].get("preferred_day")}
        """
    elif tool_call["name"] == "Question":
        # Special formatting for questions to make them clear
        display += f"""# Question for User
        {tool_call["args"].get("content")}
        """
    else:
        # Generic format for other tools
        display += f"""# Tool Call: {tool_call["name"]}
        Arguments:"""
        # Check if args is a dictionary or string
        if isinstance(tool_call["args"], dict):
            display += f"\n{json.dumps(tool_call['args'], indent=2)}\n"
        else:
            display += f"\n{tool_call['args']}\n"
    return display

def parse_gmail(email_input: dict) -> tuple[str, str, str, str, str]:
    """Parse an email input dictionary for Gmail, including the email ID.
    
    This function extends parse_email by also returning the email ID,
    which is used specifically in the Gmail integration.

    Args:
        email_input (dict): Dictionary containing email fields in any of these formats:
            Gmail schema:
                - From: Sender's email
                - To: Recipient's email
                - Subject: Email subject line
                - Body: Full email content
                - Id: Gmail message ID
            
    Returns:
        tuple[str, str, str, str, str]: Tuple containing:
            - author: Sender's name and email
            - to: Recipient's name and email
            - subject: Email subject line
            - email_thread: Full email content
            - email_id: Email ID (or None if not available)
    """

    print("!Email_input from Gmail!")
    print(email_input)

    # Gmail schema
    return (
        email_input["from"],
        email_input["to"],
        email_input["subject"],
        email_input["body"],
        email_input["id"],
    )