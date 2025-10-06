from typing import Dict, List, Optional
from langchain_core.tools import BaseTool

def get_tools(tool_names: Optional[List[str]] = None, include_gmail: bool = False) -> List[BaseTool]:
    """Get specified Gmail tools or all Gmail tools if tool_names is None.
    
    Args:
        tool_names: Optional list of tool names to include. If None, returns all Gmail tools.
        
    Returns:
        List of Gmail tool objects
    """
    all_tools = {}

        # Try importing Gmail tools safely
    if include_gmail:
        try:
            from .gmailapi.gmail_tools import (
                fetch_emails_tool,
                send_email_tool,
                check_calendar_tool,
                schedule_meeting_tool
            )

            all_tools.update({
                "fetch_emails_tool": fetch_emails_tool,
                "send_email_tool": send_email_tool,
                "check_calendar_tool": check_calendar_tool,
                "schedule_meeting_tool": schedule_meeting_tool,
            })

        except ImportError:
            # If Gmail tools aren't available, return empty list
            pass

    if tool_names is None:
        return list(all_tools.values())

    return [all_tools[name] for name in tool_names if name in all_tools]


def get_tools_by_name(tools: Optional[List[BaseTool]] = None) -> Dict[str, BaseTool]:
    """Get a dictionary of Gmail tools mapped by name."""
    if tools is None:
        tools = get_tools()
    
    return {tool.name: tool for tool in tools}

