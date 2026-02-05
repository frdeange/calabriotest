# Copyright (c) Microsoft. All rights reserved.
"""
Multi-Agent Orchestrator for OPTION2 - Direct Client with Local Tools

This module creates and runs the handoff workflow using:
- AzureOpenAIChatClient.as_agent() for agent creation
- HandoffBuilder for multi-agent orchestration
- Local tool execution (tools run in-process)

Key advantage: Tools execute locally, no external server needed.
"""

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
    RequestInfoEvent,
    WorkflowEvent,
    WorkflowOutputEvent,
)
from agent_framework.azure import AzureOpenAIChatClient
from azure.identity import AzureCliCredential
from dotenv import load_dotenv

# Import tools
from src.tools.absence_tools import (
    get_absence_types,
    get_recommended_slots,
    check_absence_availability,
    submit_absence_request,
)
from src.tools.overtime_tools import (
    get_overtime_opportunities,
    get_overtime_types,
    submit_overtime_request,
)

# Import instructions
from src.instructions.absence_instruction import (
    get_absence_agent_instructions,
    get_overtime_agent_instructions,
    get_router_agent_instructions,
)

# Import metrics
from src.metrics import (
    get_metrics,
    reset_metrics,
    print_timing_header,
    print_agent_response,
    print_handoff,
    AgentTiming,
)

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format='%(asctime)s | %(levelname)s | %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger("orchestrator")


def create_chat_client() -> AzureOpenAIChatClient:
    """Create and configure the Azure OpenAI chat client."""
    endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
    deployment = os.getenv("AZURE_OPENAI_CHAT_DEPLOYMENT_NAME", "gpt-5.2")
    api_version = os.getenv("AZURE_OPENAI_API_VERSION", "2024-12-01-preview")
    
    if not endpoint:
        raise ValueError("AZURE_OPENAI_ENDPOINT environment variable is required")
    
    logger.info(f"🔗 Connecting to Azure OpenAI: {endpoint}")
    logger.info(f"📦 Using deployment: {deployment}")
    
    return AzureOpenAIChatClient(
        credential=AzureCliCredential(),
        endpoint=endpoint,
        deployment_name=deployment,
        api_version=api_version,
    )


def create_agents(chat_client: AzureOpenAIChatClient) -> tuple[ChatAgent, ChatAgent, ChatAgent]:
    """
    Create the three agents for the workflow:
    - Router: Understands intent and routes to specialists
    - Absence Agent: Handles absence/time-off requests
    - Overtime Agent: Handles overtime work requests
    
    Returns:
        Tuple of (router_agent, absence_agent, overtime_agent)
    """
    logger.info("🤖 Creating agents...")
    
    # Router Agent - no tools, just routing logic
    router_agent = chat_client.as_agent(
        name="router_agent",
        instructions=get_router_agent_instructions(),
    )
    logger.info("  ✓ router_agent created")
    
    # Absence Agent - with absence-related tools
    absence_agent = chat_client.as_agent(
        name="absence_agent",
        instructions=get_absence_agent_instructions(),
        tools=[
            get_absence_types,
            get_recommended_slots,
            check_absence_availability,
            submit_absence_request,
        ],
    )
    logger.info("  ✓ absence_agent created (4 tools)")
    
    # Overtime Agent - with overtime-related tools
    overtime_agent = chat_client.as_agent(
        name="overtime_agent",
        instructions=get_overtime_agent_instructions(),
        tools=[
            get_overtime_opportunities,
            get_overtime_types,
            submit_overtime_request,
        ],
    )
    logger.info("  ✓ overtime_agent created (3 tools)")
    
    return router_agent, absence_agent, overtime_agent


def build_workflow(
    router_agent: ChatAgent,
    absence_agent: ChatAgent,
    overtime_agent: ChatAgent
) -> "Workflow":
    """
    Build the handoff workflow with routing rules.
    
    Flow:
        User → Router → Absence/Overtime Agent → Router → Done
    """
    logger.info("🔄 Building handoff workflow...")
    
    workflow = (
        HandoffBuilder(
            name="absence_overtime_handoff",
            participants=[router_agent, absence_agent, overtime_agent],
        )
        .with_start_agent(router_agent)
        .add_handoff(router_agent, [absence_agent, overtime_agent])
        .add_handoff(absence_agent, [router_agent])
        .add_handoff(overtime_agent, [router_agent])
        .build()
    )
    
    logger.info("  ✓ Workflow built: router ↔ absence_agent ↔ overtime_agent")
    return workflow


# Global state for tracking responses
last_response_id: str | None = None
current_agent: str | None = None
agent_start_time: float | None = None


def _display_event(event: WorkflowEvent, metrics=None) -> list[RequestInfoEvent]:
    """Display workflow events with timing information. Returns any pending requests."""
    global last_response_id, current_agent, agent_start_time
    
    pending_requests: list[RequestInfoEvent] = []
    
    # Check for user input requests
    if isinstance(event, RequestInfoEvent):
        pending_requests.append(event)
        return pending_requests
    
    # Handle AgentRunUpdateEvent - this is where streaming text comes from
    if isinstance(event, AgentRunUpdateEvent) and event.data:
        update: AgentResponseUpdate = event.data
        
        # Track agent switching
        if update.author_name and update.author_name != current_agent:
            if current_agent and agent_start_time:
                elapsed = time.perf_counter() - agent_start_time
                logger.info(f"⏱️  Agent '{current_agent}' completed in {elapsed:.2f}s")
                if metrics:
                    metrics.agent_timings.append(AgentTiming(
                        name=current_agent,
                        start_time=agent_start_time,
                        end_time=time.perf_counter(),
                        duration=elapsed
                    ))
            
            current_agent = update.author_name
            agent_start_time = time.perf_counter()
            logger.info(f"🔄 Routing to agent: '{current_agent}'")
        
        if update.text:
            if update.response_id != last_response_id:
                last_response_id = update.response_id
                print(f"\n🤖 [{current_agent}]: ", flush=True, end="")
            print(update.text, flush=True, end="")
    
    # Handle WorkflowOutputEvent - may contain AgentResponseUpdate
    elif isinstance(event, WorkflowOutputEvent):
        data = event.data
        if isinstance(data, AgentResponseUpdate):
            update = data
            if update.author_name and update.author_name != current_agent:
                current_agent = update.author_name
                logger.info(f"🔄 Routing to agent: '{current_agent}'")
            
            if update.text:
                if update.response_id != last_response_id:
                    last_response_id = update.response_id
                    print(f"\n🤖 [{current_agent}]: ", flush=True, end="")
                print(update.text, flush=True, end="")
    
    return pending_requests


async def run_conversation(workflow, initial_input: str, metrics=None):
    """
    Run a full conversation with the workflow, handling multiple turns.
    
    Uses send_responses_streaming to continue conversations properly.
    """
    global last_response_id, current_agent, agent_start_time
    last_response_id = None
    current_agent = None
    agent_start_time = None
    
    pending_requests: list[RequestInfoEvent] = []
    
    # Initial run
    async for event in workflow.run_stream(initial_input):
        requests = _display_event(event, metrics)
        pending_requests.extend(requests)
    
    # Log final agent timing for this turn
    if current_agent and agent_start_time:
        elapsed = time.perf_counter() - agent_start_time
        logger.info(f"⏱️  Agent '{current_agent}' completed in {elapsed:.2f}s")
        if metrics:
            metrics.agent_timings.append(AgentTiming(
                name=current_agent,
                start_time=agent_start_time,
                end_time=time.perf_counter(),
                duration=elapsed
            ))
    
    print()  # Add newline after response
    return pending_requests


async def continue_conversation(workflow, pending_requests: list[RequestInfoEvent], user_input: str, metrics=None):
    """
    Continue an existing conversation by responding to pending requests.
    """
    global last_response_id, current_agent, agent_start_time
    last_response_id = None
    current_agent = None
    agent_start_time = None
    
    if not pending_requests:
        logger.warning("No pending requests to respond to")
        return []
    
    # Build responses for all pending requests
    responses = {
        req.request_id: [ChatMessage("user", text=user_input)]
        for req in pending_requests
    }
    
    new_pending: list[RequestInfoEvent] = []
    
    # Continue the workflow with the responses
    async for event in workflow.send_responses_streaming(responses):
        requests = _display_event(event, metrics)
        new_pending.extend(requests)
    
    # Log final agent timing for this turn
    if current_agent and agent_start_time:
        elapsed = time.perf_counter() - agent_start_time
        logger.info(f"⏱️  Agent '{current_agent}' completed in {elapsed:.2f}s")
        if metrics:
            metrics.agent_timings.append(AgentTiming(
                name=current_agent,
                start_time=agent_start_time,
                end_time=time.perf_counter(),
                duration=elapsed
            ))
    
    print()  # Add newline after response
    return new_pending


async def main():
    """Main entry point for the orchestrator."""
    print("\n" + "═" * 64)
    print("  🤖 Multi-Agent Absence & Overtime Workflow (OPTION2)")
    print("     Direct Client with Local Tools")
    print("═" * 64)
    
    try:
        # Initialize
        chat_client = create_chat_client()
        router, absence, overtime = create_agents(chat_client)
        workflow = build_workflow(router, absence, overtime)
        
        print("\n" + "─" * 64)
        print("  Type your request (or 'quit' to exit, 'metrics' for report)")
        print("  Type 'new' to start a fresh conversation")
        print("─" * 64)
        
        metrics = get_metrics()
        pending_requests: list[RequestInfoEvent] = []
        conversation_active = False
        
        while True:
            try:
                user_input = input("\n👤 You: ").strip()
                
                if not user_input:
                    continue
                
                if user_input.lower() == 'quit':
                    print("\n👋 Goodbye!")
                    break
                
                if user_input.lower() == 'metrics':
                    metrics.print_report()
                    continue
                
                if user_input.lower() == 'reset':
                    reset_metrics()
                    print("📊 Metrics reset.")
                    continue
                
                if user_input.lower() == 'new':
                    # Start a fresh conversation
                    workflow = build_workflow(router, absence, overtime)
                    pending_requests = []
                    conversation_active = False
                    print("🔄 New conversation started.")
                    continue
                
                # Run the workflow
                print_timing_header()
                with metrics.track_workflow():
                    if conversation_active and pending_requests:
                        # Continue existing conversation
                        pending_requests = await continue_conversation(
                            workflow, pending_requests, user_input, metrics
                        )
                    else:
                        # Start new conversation
                        pending_requests = await run_conversation(
                            workflow, user_input, metrics
                        )
                        conversation_active = True
                
            except KeyboardInterrupt:
                print("\n\n👋 Interrupted. Goodbye!")
                break
            except Exception as e:
                logger.error(f"Error during conversation: {e}")
                import traceback
                traceback.print_exc()
                print(f"\n❌ Error: {e}")
        
        # Print final metrics
        print("\n" + "═" * 64)
        print("  📊 Final Timing Report")
        print("═" * 64)
        metrics.print_report()
        
    except Exception as e:
        logger.error(f"Failed to initialize: {e}")
        print(f"\n❌ Initialization error: {e}")
        print("\nMake sure you have:")
        print("  1. Run 'az login' for Azure authentication")
        print("  2. Set AZURE_OPENAI_ENDPOINT in .env")
        print("  3. Set AZURE_OPENAI_DEPLOYMENT_NAME in .env")
        raise


if __name__ == "__main__":
    asyncio.run(main())
