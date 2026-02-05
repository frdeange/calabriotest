# Copyright (c) Microsoft. All rights reserved.
"""
Absence Tools for OPTION2 - Direct Client with Local Execution

Using the correct MAF pattern:
- @tool(approval_mode="never_require") decorator
- Annotated types with pydantic Field for parameter descriptions

All tools return mock data for POC validation.
"""

from typing import Annotated
from pydantic import Field
from agent_framework import tool


@tool(approval_mode="never_require")
def get_absence_types(
    start_date: Annotated[str, Field(description="Start date in YYYY-MM-DD format")],
    end_date: Annotated[str, Field(description="End date in YYYY-MM-DD format")],
    mode: Annotated[str, Field(description="Either 'full' for full-day or 'partial' for part-day absence")]
) -> str:
    """Get available absence types for a date range.
    
    Returns JSON with absence types including: name, available start dates,
    person account status, and remaining balance if applicable.
    """
    return f'''{{"mode": "{mode}", "start_date": "{start_date}", "end_date": "{end_date}",
"absence_types": [
  {{"name": "Holiday", "available_dates": ["{start_date}"], "has_balance": false}},
  {{"name": "Part Day", "available_dates": ["{end_date}"], "has_balance": true, "remaining": "200 minutes"}},
  {{"name": "Sick Leave", "available_dates": ["{start_date}"], "has_balance": false}},
  {{"name": "AWOL", "available_dates": ["{start_date}"], "has_balance": false}},
  {{"name": "Paternity", "available_dates": ["{start_date}"], "has_balance": true, "remaining": "10 days"}}
]}}'''


@tool(approval_mode="never_require")
def get_recommended_slots(
    date: Annotated[str, Field(description="Date in YYYY-MM-DD format")],
    absence_type: Annotated[str, Field(description="The selected absence type (e.g., 'Holiday', 'Sick Leave')")],
    start_time: Annotated[str, Field(description="Requested start time (e.g., '1PM', '13:00')")],
    end_time: Annotated[str, Field(description="Requested end time (e.g., '4PM', '16:00')")]
) -> str:
    """Get recommended absence slots for a specific date, absence type, and time range.
    Used for part-day absences to show available time slots.
    
    Returns JSON with recommended slots based on minimum duration and increment rules.
    """
    return f'''{{"date": "{date}", "absence_type": "{absence_type}", 
"requested_time": "{start_time} - {end_time}",
"recommended_slots": [
  {{"slot": "1:00 PM - 4:00 PM", "duration": "3 hours"}},
  {{"slot": "1:00 PM - 3:00 PM", "duration": "2 hours"}},
  {{"slot": "2:00 PM - 4:00 PM", "duration": "2 hours"}}
],
"minimum_duration": "1 hour",
"increment": "30 minutes"}}'''


@tool(approval_mode="never_require")
def check_absence_availability(
    date: Annotated[str, Field(description="Date in YYYY-MM-DD format")],
    absence_type: Annotated[str, Field(description="The absence type to check")]
) -> str:
    """Check if a specific absence type is available for a given date.
    If not available, returns alternative absence types that can be used.
    
    Returns JSON indicating availability and alternatives if not available.
    """
    return f'''{{"date": "{date}", "absence_type": "{absence_type}", 
"available": true,
"message": "{absence_type} is available for {date}"}}'''


@tool(approval_mode="never_require")
def submit_absence_request(
    start_date: Annotated[str, Field(description="Start date in YYYY-MM-DD format")],
    end_date: Annotated[str, Field(description="End date in YYYY-MM-DD format")],
    absence_type: Annotated[str, Field(description="The selected absence type")],
    mode: Annotated[str, Field(description="Either 'full' for full-day or 'partial' for part-day")],
    start_time: Annotated[str, Field(description="Start time for part-day absence (optional)")] = "",
    end_time: Annotated[str, Field(description="End time for part-day absence (optional)")] = "",
    subject: Annotated[str, Field(description="Request subject (optional)")] = "",
    message: Annotated[str, Field(description="Additional message (optional)")] = ""
) -> str:
    """Submit an absence request (full-day or part-day).
    
    Returns JSON with request status (approved, pending, denied) and request ID.
    """
    time_info = f', "time": "{start_time} - {end_time}"' if start_time and end_time else ""
    return f'''{{"status": "approved",
"message": "Absence request submitted successfully",
"request_id": "ABS-2026-001",
"details": {{
  "type": "{absence_type}",
  "mode": "{mode}",
  "dates": "{start_date} to {end_date}"{time_info}
}}}}'''
