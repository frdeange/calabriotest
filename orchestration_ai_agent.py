# Copyright (c) Microsoft. All rights reserved.
import os
import asyncio
import logging
import time
from typing import cast

from agent_framework import (
    AgentResponseUpdate,
    AgentRunUpdateEvent,
    ChatAgent,
    ChatMessage,
    HandoffBuilder,
    WorkflowEvent,
    WorkflowOutputEvent,
    tool,
)
from agent_framework.azure import AzureOpenAIChatClient,AzureAIProjectAgentProvider
from azure.identity import AzureCliCredential
from instruction.absence_instruction import get_absence_agent_instructions
from dotenv import load_dotenv

load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger("orchestrator")

"""Multi-agent workflow for Absence and Overtime requests.

This sample demonstrates a handoff workflow where a router agent understands
user intent and routes requests to specialized agents (absence_agent, overtime_agent).

Routing Pattern:
    User -> Router -> Absence Agent / Overtime Agent -> Router -> Final Output

Prerequisites:
    - `az login` (Azure CLI authentication)
    - Environment variables for AzureOpenAIChatClient (AZURE_OPENAI_ENDPOINT, etc.)

Key Concepts:
    - Intent-based routing: router understands user request and delegates
    - Specialized agents: each agent has domain-specific tools
"""


# ─────────────────────────────────────────────────────────
# Absence Agent Tools
# ─────────────────────────────────────────────────────────
@tool(approval_mode="always_require")
def get_absence_types(start_date: str, end_date: str, mode: str) -> str:
    """Get available absence types for a date range.
    
    Args:
        start_date: Start date in YYYY-MM-DD format
        end_date: End date in YYYY-MM-DD format  
        mode: Either 'full' for full-day or 'partial' for part-day absence
    
    Returns:
        JSON with absence types including: name, available start dates (SD), 
        person account status (PA), and remaining balance if applicable.
        Example: Holiday(SD: 13-Oct), Part Day(PA: Yes, Remaining: 200 minutes)(SD: 15-Oct)
    """
    # TODO: Integrate with actual AbsencePlugin.get_all_absence_types()
    return f'''{{"mode": "{mode}", "start_date": "{start_date}", "end_date": "{end_date}",
"absence_types": [
  {{"name": "Holiday", "available_dates": ["{start_date}"], "has_balance": false}},
  {{"name": "Part Day", "available_dates": ["{end_date}"], "has_balance": true, "remaining": "200 minutes"}},
  {{"name": "Sick Leave", "available_dates": ["{start_date}"], "has_balance": false}},
  {{"name": "AWOL", "available_dates": ["{start_date}"], "has_balance": false}},
  {{"name": "Paternity", "available_dates": ["{start_date}"], "has_balance": true, "remaining": "10 days"}}
]}}'''


@tool(approval_mode="always_require")
def get_recommended_slots(date: str, absence_type: str, start_time: str, end_time: str) -> str:
    """Get recommended absence slots for a specific date, absence type, and time range.
    Used for part-day absences to show available time slots.
    
    Args:
        date: Date in YYYY-MM-DD format
        absence_type: The selected absence type (e.g., 'Holiday', 'Sick Leave')
        start_time: Requested start time (e.g., '1PM', '13:00')
        end_time: Requested end time (e.g., '4PM', '16:00')
    
    Returns:
        JSON with recommended slots based on minimum duration and increment rules.
        If absence type not available for date, suggests alternatives.
    """
    # TODO: Integrate with actual AbsencePlugin.get_part_day_recommended_slots_with_absence_type()
    return f'''{{"date": "{date}", "absence_type": "{absence_type}", 
"requested_time": "{start_time} - {end_time}",
"recommended_slots": [
  {{"slot": "1:00 PM - 4:00 PM", "duration": "3 hours"}},
  {{"slot": "1:00 PM - 3:00 PM", "duration": "2 hours"}},
  {{"slot": "2:00 PM - 4:00 PM", "duration": "2 hours"}}
],
"minimum_duration": "1 hour",
"increment": "30 minutes"}}'''


@tool(approval_mode="always_require")
def check_absence_availability(date: str, absence_type: str) -> str:
    """Check if a specific absence type is available for a given date.
    If not available, returns alternative absence types that can be used.
    
    Args:
        date: Date in YYYY-MM-DD format
        absence_type: The absence type to check
    
    Returns:
        JSON indicating availability and alternatives if not available.
    """
    # TODO: Integrate with actual AbsencePlugin
    return f'''{{"date": "{date}", "absence_type": "{absence_type}", 
"available": true,
"message": "{absence_type} is available for {date}"}}'''


@tool(approval_mode="always_require")
def submit_absence_request(start_date: str, end_date: str, absence_type: str, mode: str, start_time: str, end_time: str, subject: str, message: str) -> str:
    """Submit an absence request (full-day or part-day).
    
    Args:
        start_date: Start date in YYYY-MM-DD format
        end_date: End date in YYYY-MM-DD format
        absence_type: The type of absence (e.g., 'Holiday', 'Paternity')
        mode: 'full' for full-day or 'partial' for part-day
        start_time: Start time for part-day (empty for full-day)
        end_time: End time for part-day (empty for full-day)
        subject: Subject line for the request (optional)
        message: Message/reason for the absence (optional)
    
    Returns:
        JSON with request status (approved, pending, waitlisted, denied)
    """
    # TODO: Integrate with actual AbsencePlugin.add_full_day_absence_request() or add_part_day_absence_request()
    time_info = f" from {start_time} to {end_time}" if mode == "partial" else ""
    return f'''{{"status": "pending",
"message": "Absence request submitted successfully",
"details": {{
  "type": "{absence_type}",
  "date_range": "{start_date} to {end_date}",
  "mode": "{mode}"{f', "time": "{start_time} - {end_time}"' if mode == "partial" else ""}
}}}}'''


# ─────────────────────────────────────────────────────────
# Overtime Agent Tools
# ─────────────────────────────────────────────────────────
@tool(approval_mode="always_require")
def get_overtime_opportunities(date: str) -> str:
    """Get available overtime slots for a specific date.
    Shows when overtime can be worked (before/after shift).
    
    Args:
        date: Date in YYYY-MM-DD format
    
    Returns:
        JSON with available overtime time slots, minimum lunch time,
        maximum continuous work time, and minimum rest time.
    """
    # TODO: Integrate with actual OvertimePlugin.get_all_overtime_opportunities()
    return f'''{{"date": "{date}",
"available_slots": [
  {{"slot": "6:00 AM - 8:00 AM", "type": "before_shift"}},
  {{"slot": "5:00 PM - 7:00 PM", "type": "after_shift"}}
],
"rules": {{
  "max_continuous_work": "4 hours",
  "min_lunch_time": "30 minutes",
  "min_rest_time": "11 hours"
}}}}'''


@tool(approval_mode="always_require")
def get_overtime_types(date: str) -> str:
    """Get available overtime types for a specific date.
    
    Args:
        date: Date in YYYY-MM-DD format
    
    Returns:
        JSON with available overtime types (e.g., Overtime Paid, Overtime Time)
    """
    # TODO: Integrate with actual OvertimePlugin.get_all_overtime_types()
    return f'''{{"date": "{date}",
"overtime_types": [
  {{"name": "Overtime Paid", "description": "Paid overtime compensation"}},
  {{"name": "Overtime Time", "description": "Compensatory time off"}}
]}}'''


@tool(approval_mode="always_require")
def submit_overtime_request(date: str, start_time: str, end_time: str, overtime_type: str) -> str:
    """Submit an overtime request.
    
    Args:
        date: Date in YYYY-MM-DD format
        start_time: Start time (e.g., '5:00 PM', '17:00')
        end_time: End time (e.g., '6:00 PM', '18:00')
        overtime_type: Type of overtime (e.g., 'Overtime Paid', 'Overtime Time')
    
    Returns:
        JSON with request status and summary.
    """
    # TODO: Integrate with actual OvertimePlugin.add_overtime_request()
    return f'''{{"status": "submitted",
"message": "Your overtime request has been submitted successfully",
"summary": {{
  "date": "{date}",
  "time": "{start_time} to {end_time}",
  "type": "{overtime_type}",
  "subject": "Overtime request from {start_time} to {end_time} on {date}"
}}}}'''


# ─────────────────────────────────────────────────────────
# Agent Creation
# ─────────────────────────────────────────────────────────
def create_agents(
    chat_client: AzureOpenAIChatClient,
) -> tuple[ChatAgent, ChatAgent, ChatAgent]:
    """Create router and specialist agents for absence/overtime workflows."""
    
    router_agent = chat_client.as_agent(
        instructions=(
            "You are an intelligent router agent. Your job is to understand the user's intent "
            "and route their request to the appropriate specialist agent.\n\n"
            "Available specialists:\n"
            "- absence_agent: Handles all absence-related requests (vacation, sick leave, time off, PTO, leave requests)\n"
            "- overtime_agent: Handles all overtime-related requests (extra hours, overtime slots, OT requests)\n\n"
            "When a user makes a request:\n"
            "1. Analyze the intent of the request\n"
            "2. Route to the appropriate specialist agent\n"
            "3. After the specialist completes the task, summarize the result for the user\n\n"
            "If the request is unclear, ask clarifying questions before routing."
        ),
        name="router_agent",
    )

    absence_agent = chat_client.as_agent(
        instructions=get_absence_agent_instructions(),
        name="absence_agent",
        tools=[get_absence_types, get_recommended_slots, check_absence_availability, submit_absence_request],
    )

    overtime_agent = chat_client.as_agent(
        instructions=(
            "You are an overtime specialist agent. You help users with overtime requests.\n\n"
            "WORKFLOW:\n"
            "1. Ask user for the time range they want to work overtime (e.g., 5PM-6PM)\n"
            "2. Use get_overtime_opportunities to check available slots for today/specified date\n"
            "3. Use get_overtime_types to show overtime type options (Overtime Paid, Overtime Time)\n"
            "4. When user selects a type, show a summary with:\n"
            "   - Date, Time, Overtime type, Subject, Message\n"
            "5. Ask user to confirm the request\n"
            "6. When user confirms (ok/yes/confirm), use submit_overtime_request to submit\n\n"
            "Always show a clear summary before submitting.\n"
            "When done, hand off back to router_agent with the result."
        ),
        name="overtime_agent",
        tools=[get_overtime_opportunities, get_overtime_types, submit_overtime_request],
    )

    return router_agent, absence_agent, overtime_agent


last_response_id: str | None = None
current_agent: str | None = None
agent_start_time: float | None = None


def _display_event(event: WorkflowEvent) -> None:
    """Print agent responses to the user with logging."""
    global last_response_id, current_agent, agent_start_time
    
    if isinstance(event, AgentRunUpdateEvent) and event.data:
        update: AgentResponseUpdate = event.data
        
        # Log agent routing/switching
        if update.author_name and update.author_name != current_agent:
            if current_agent and agent_start_time:
                elapsed = time.time() - agent_start_time
                logger.info(f"Agent '{current_agent}' completed in {elapsed:.2f}s")
            
            current_agent = update.author_name
            agent_start_time = time.time()
            logger.info(f"Routing to agent: '{current_agent}'")
        
        if not update.text:
            return
            
        if update.response_id != last_response_id:
            last_response_id = update.response_id
            print("\nAssistant: ", flush=True, end="")
        print(update.text, flush=True, end="")

# ─────────────────────────────────────────────────────────
# Azure Foundry Agent Creation
# ─────────────────────────────────────────────────────────
async def create_foundry_agents(
    provider: AzureAIProjectAgentProvider,
) -> tuple[ChatAgent, ChatAgent, ChatAgent]:
    """Create Azure AI Foundry managed agents."""
    
    # 1. Create Router Agent in Foundry
    router_agent = await provider.create_agent(
        model="gpt-4.1", # Replace with your deployment name
        instructions=(
            "You are an intelligent router agent. Your job is to understand the user's intent "
            "and route their request to the appropriate specialist agent.\n\n"
            "Available specialists:\n"
            "- absence_agent: Handles all absence-related requests\n"
            "- overtime_agent: Handles all overtime-related requests\n"
            "If the request is unclear, ask clarifying questions before routing."
        ),
        name="router-agent",
    )

    # 2. Create Absence Agent in Foundry
    absence_agent = await provider.create_agent(
        model="gpt-4.1",
        instructions=get_absence_agent_instructions(),
        name="absence-agent",
        tools=[get_absence_types, get_recommended_slots, check_absence_availability, submit_absence_request],
    )

    # 3. Create Overtime Agent in Foundry
    overtime_agent = await provider.create_agent(
        model="gpt-4.1",
        instructions=(
            "You are an overtime specialist agent. You help users with overtime requests.\n"
            "Use the provided tools to check opportunities and submit requests.\n"
            "When done, hand off back to router_agent."
        ),
        name="overtime-agent",
        tools=[get_overtime_opportunities, get_overtime_types, submit_overtime_request],
    )

    return router_agent, absence_agent, overtime_agent

async def main() -> None:
    """Run a handoff workflow for absence and overtime requests."""
    # chat_client = AzureOpenAIChatClient(credential=AzureCliCredential())
    # router_agent, absence_agent, overtime_agent = create_agents(chat_client)
    con_str=os.getenv("AZURE_OPENAI_CONNECTION_STRING")
    credential = AzureCliCredential()
    async with AzureAIProjectAgentProvider(project_endpoint=con_str, credential=credential) as provider:
        # Provision the cloud agents
        router_agent, absence_agent, overtime_agent = await create_foundry_agents(provider)

    # Build the workflow - each turn waits for user input
    workflow = (
        HandoffBuilder(
            name="absence_overtime_handoff",
            participants=[router_agent, absence_agent, overtime_agent],
        )
        .with_start_agent(router_agent)
        .add_handoff(router_agent, [absence_agent, overtime_agent])
        .add_handoff(absence_agent, [router_agent])  # Absence agent hands back to router
        .add_handoff(overtime_agent, [router_agent])  # Overtime agent hands back to router
        .build()
    )

    print("=" * 60)
    print("Absence & Overtime Request Assistant")
    print("Type 'exit' to quit")
    print("=" * 60)
    
    while True:
        global last_response_id, current_agent, agent_start_time
        last_response_id = None
        current_agent = None
        agent_start_time = None
        
        request = input("\nYou: ").strip()
        
        if not request:
            continue
            
        if request.lower() == "exit":
            print("Goodbye!")
            break
        
        request_start = time.time()
        logger.info(f"User request: '{request[:50]}...'" if len(request) > 50 else f"User request: '{request}'")
        
        async for event in workflow.run_stream(request):
            _display_event(event)
        
        # Log final agent timing
        if current_agent and agent_start_time:
            elapsed = time.time() - agent_start_time
            logger.info(f"Agent '{current_agent}' completed in {elapsed:.2f}s")
        
        total_time = time.time() - request_start
        logger.info(f"Total request time: {total_time:.2f}s")
        
        print()  # Add newline after response


if __name__ == "__main__":
    asyncio.run(main())