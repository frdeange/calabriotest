# Copyright (c) Microsoft. All rights reserved.
"""
OPTION1 Orchestrator

Uses Microsoft Agent Framework with AzureAIProjectAgentProvider (SDK V2) for Azure AI Agent Service.
Agents are created IN the Azure AI Agent Service using the new Foundry Responses API.
MCP tools are accessed via HostedMCPTool (service-side execution).
HandoffBuilder manages the multi-agent workflow.
"""

import asyncio
import os
from collections.abc import AsyncIterable
from typing import cast

from azure.identity.aio import AzureCliCredential
from dotenv import load_dotenv

# Microsoft Agent Framework imports
from agent_framework import (
    AgentResponse,
    AgentResponseUpdate,
    AgentRunUpdateEvent,
    ChatAgent,
    ChatMessage,
    HandoffBuilder,
    HandoffAgentUserRequest,
    HandoffSentEvent,
    HostedMCPTool,
    RequestInfoEvent,
    WorkflowEvent,
    WorkflowOutputEvent,
    WorkflowRunState,
    WorkflowStatusEvent,
    tool,
)
from agent_framework.azure import AzureAIProjectAgentProvider

from .instructions.absence_instruction import (
    get_absence_agent_instructions,
    get_overtime_agent_instructions,
    get_router_agent_instructions,
)

# Load environment variables
load_dotenv()


class Option1Orchestrator:
    """
    Orchestrator using Azure AI Agent Service with HandoffBuilder.
    
    Key differences from OPTION2:
    - Agents are created IN the Azure AI Agent Service (not local)
    - MCP tools are executed by the service via HostedMCPTool
    - Uses AzureAIProjectAgentProvider (SDK V2) instead of AzureOpenAIChatClient
    - HandoffBuilder manages the multi-agent workflow
    """
    
    def __init__(self):
        # Azure AI Project configuration from environment
        self.project_endpoint = os.getenv("AZURE_AI_PROJECT_ENDPOINT")
        self.model_deployment = os.getenv("AZURE_AI_MODEL_DEPLOYMENT_NAME", "gpt-4o")
        self.mcp_server_url = os.getenv("MCP_SERVER_URL", "https://learn.microsoft.com/api/mcp")
        
        # Azure credential
        self.credential: AzureCliCredential | None = None
        
        # Agent provider (creates agents in Azure AI Agent Service using V2 Responses API)
        self.provider: AzureAIProjectAgentProvider | None = None
        
        # Agents
        self.router_agent: ChatAgent | None = None
        self.absence_agent: ChatAgent | None = None
        self.overtime_agent: ChatAgent | None = None
        
        # Workflow
        self.workflow = None
        
    async def setup(self) -> None:
        """Initialize the orchestrator with agents and handoff configuration."""
        
        print("🔧 Setting up OPTION1 Orchestrator...")
        print(f"   Project Endpoint: {self.project_endpoint}")
        print(f"   Model: {self.model_deployment}")
        print(f"   MCP Server: {self.mcp_server_url}")
        
        # Create Azure credential
        self.credential = AzureCliCredential()
        
        # Create the agent provider using V2 (Responses API) - reads AZURE_AI_PROJECT_ENDPOINT from env
        self.provider = AzureAIProjectAgentProvider(credential=self.credential)
        
        # Enter the async context for the provider
        await self.provider.__aenter__()
        
        # Create HostedMCPTool - the Azure AI Agent Service will call the MCP server directly
        # Using Microsoft Learn MCP as placeholder (no auth required)
        mcp_tool = HostedMCPTool(
            name="Microsoft Learn MCP",
            url=self.mcp_server_url,
        )
        
        # ============================================================
        # Create handoff tools manually
        # Azure AI Responses API requires tools to be defined at agent creation time,
        # NOT at request time. HandoffBuilder adds tools to cloned agents locally,
        # but that doesn't work with Azure AI agents since tools are already fixed.
        # Solution: Create handoff tools upfront and pass them to create_agent.
        # ============================================================
        
        @tool(name="handoff_to_AbsenceAgent", description="Transfer the conversation to AbsenceAgent for handling time-off, vacation, holiday, sick leave requests")
        def handoff_to_absence(context: str = "") -> str:
            """Transfer to the absence specialist."""
            return "Handoff to AbsenceAgent"
        
        @tool(name="handoff_to_OvertimeAgent", description="Transfer the conversation to OvertimeAgent for handling overtime work scheduling requests")
        def handoff_to_overtime(context: str = "") -> str:
            """Transfer to the overtime specialist."""
            return "Handoff to OvertimeAgent"
        
        @tool(name="handoff_to_RouterAgent", description="Transfer the conversation back to RouterAgent when the current task is complete or user needs different help")
        def handoff_to_router(context: str = "") -> str:
            """Transfer back to the router."""
            return "Handoff to RouterAgent"
        
        print("📦 Creating agents in Azure AI Agent Service...")
        
        # Create Router Agent WITH handoff tools
        # Note: SDK V2 doesn't allow underscores in agent names
        self.router_agent = await self.provider.create_agent(
            name="RouterAgent",
            instructions=get_router_agent_instructions(),
            # Router needs handoff tools to transfer to specialists
            tools=[handoff_to_absence, handoff_to_overtime],
        )
        print("   ✅ RouterAgent created (with handoff tools)")
        
        # Create Absence Agent with MCP tools + handoff back to router
        self.absence_agent = await self.provider.create_agent(
            name="AbsenceAgent",
            instructions=get_absence_agent_instructions(),
            tools=[mcp_tool, handoff_to_router],
        )
        print("   ✅ AbsenceAgent created (with MCP + handoff)")
        
        # Create Overtime Agent with MCP tools + handoff back to router
        self.overtime_agent = await self.provider.create_agent(
            name="OvertimeAgent",
            instructions=get_overtime_agent_instructions(),
            tools=[mcp_tool, handoff_to_router],
        )
        print("   ✅ OvertimeAgent created (with MCP + handoff)")
        
        # Configure handoffs using HandoffBuilder
        print("🔗 Configuring HandoffBuilder workflow...")
        
        # ============================================================
        # Monkey-patch HandoffBuilder._apply_auto_tools to SKIP existing handoff tools
        # instead of raising an error. This is needed because Azure AI Agent Service
        # requires tools to be defined at agent creation time, so we pre-create handoff
        # tools, but HandoffBuilder also tries to create them.
        # ============================================================
        from agent_framework._workflows._handoff import HandoffAgentExecutor, HandoffConfiguration
        from agent_framework._workflows._agent_utils import resolve_agent_id
        from agent_framework._tools import FunctionTool
        from typing import Any, Sequence
        
        original_apply_auto_tools = HandoffAgentExecutor._apply_auto_tools
        
        def patched_apply_auto_tools(self, agent: ChatAgent, targets: Sequence[HandoffConfiguration]) -> None:
            """Modified version that skips existing handoff tools instead of raising error."""
            default_options = agent.default_options
            existing_tools = list(default_options.get("tools") or [])
            existing_names = {getattr(t, "name", "") for t in existing_tools if hasattr(t, "name")}
            
            new_tools: list[FunctionTool[Any, Any]] = []
            for target in targets:
                tool = self._create_handoff_tool(target.target_id, target.description)
                if tool.name in existing_names:
                    # SKIP instead of raising error - the tool already exists
                    continue
                new_tools.append(tool)
            
            if new_tools:
                default_options["tools"] = existing_tools + new_tools
            else:
                default_options["tools"] = existing_tools
        
        # Apply the patch
        HandoffAgentExecutor._apply_auto_tools = patched_apply_auto_tools
        
        # Build the handoff workflow
        # - participants: All agents that can participate
        # - with_start_agent: Router is the entry point
        # - add_handoff: Define routing relationships
        self.workflow = (
            HandoffBuilder(
                name="calabrio_workforce_handoff",
                participants=[self.router_agent, self.absence_agent, self.overtime_agent],
            )
            .with_start_agent(self.router_agent)
            # Router can hand off to specialists
            .add_handoff(self.router_agent, [self.absence_agent, self.overtime_agent])
            # Specialists can hand back to router when done
            .add_handoff(self.absence_agent, [self.router_agent])
            .add_handoff(self.overtime_agent, [self.router_agent])
            # Custom termination: end when user says "exit" or conversation naturally concludes
            .with_termination_condition(
                lambda conversation: (
                    len(conversation) > 0 
                    and any(
                        keyword in conversation[-1].text.lower() 
                        for keyword in ["goodbye", "thank you", "thanks", "exit", "quit"]
                    )
                )
            )
            .build()
        )
        
        print("✅ OPTION1 Orchestrator setup complete!")
        print("")
        
    async def run_conversation_loop(self) -> None:
        """Run an interactive conversation loop using the HandoffBuilder workflow."""
        
        print("=" * 60)
        print("OPTION1: Azure AI Agent Service + MCP with HandoffBuilder")
        print("=" * 60)
        print("Type 'exit' or 'quit' to end the conversation.")
        print("-" * 60)
        print("")
        
        if not self.workflow:
            raise RuntimeError("Orchestrator not initialized. Call setup() first.")
        
        # Collect user inputs for the workflow
        user_inputs: list[str] = []
        input_index = 0
        
        # Get initial user input
        initial_input = input("You: ").strip()
        if initial_input.lower() in ["exit", "quit"]:
            print("\n👋 Goodbye!")
            return
        
        # Run the workflow with streaming using run_stream() method
        # run_stream() is an async generator that yields WorkflowEvent
        pending_requests: list[RequestInfoEvent] = []
        last_response_id: str | None = None
        
        async for event in self.workflow.run_stream(initial_input):
            last_response_id = await self._handle_workflow_event(event, last_response_id)
            
            # Collect pending requests for user input
            if isinstance(event, RequestInfoEvent):
                if isinstance(event.data, HandoffAgentUserRequest):
                    pending_requests.append(event)
            
            # Check workflow status
            if isinstance(event, WorkflowStatusEvent):
                if event.state == WorkflowRunState.IDLE:
                    print("\n\n✅ Workflow completed.")
                    return
                elif event.state == WorkflowRunState.FAILED:
                    print(f"\n\n❌ Workflow error: {event}")
                    return
        
        # Process pending requests in a loop
        while pending_requests:
            # Get user response
            user_response = input("\nYou: ").strip()
            if user_response.lower() in ["exit", "quit"]:
                print("\n👋 Goodbye!")
                return
            
            # Send responses to all pending requests
            responses = {
                req.request_id: HandoffAgentUserRequest.create_response(user_response) 
                for req in pending_requests
            }
            pending_requests.clear()
            last_response_id = None  # Reset for new conversation turn
            
            # Continue the workflow with user responses
            async for event in self.workflow.send_responses_streaming(responses):
                last_response_id = await self._handle_workflow_event(event, last_response_id)
                
                if isinstance(event, RequestInfoEvent):
                    if isinstance(event.data, HandoffAgentUserRequest):
                        pending_requests.append(event)
                
                if isinstance(event, WorkflowStatusEvent):
                    if event.state == WorkflowRunState.IDLE:
                        print("\n\n✅ Workflow completed.")
                        return
                    elif event.state == WorkflowRunState.FAILED:
                        print(f"\n\n❌ Workflow error: {event}")
                        return
                    
    async def _handle_workflow_event(self, event: WorkflowEvent, last_response_id: str | None = None) -> str | None:
        """Handle different types of workflow events.
        
        Returns the response_id for tracking streaming continuity.
        """
        
        if isinstance(event, HandoffSentEvent):
            # Handoff between agents
            print(f"\n🔄 [Handoff: {event.source} → {event.target}]")
            
        elif isinstance(event, AgentRunUpdateEvent):
            # Streaming update from agent - THIS IS THE KEY EVENT FOR STREAMING!
            data = event.data
            if isinstance(data, AgentResponseUpdate) and data.text:
                author = data.author_name or event.executor_id
                response_id = getattr(data, 'response_id', None)
                
                # Print newline when switching to different response/agent
                if response_id != last_response_id:
                    if last_response_id is not None:
                        print()  # Newline between different responses
                    print(f"\n[{author}]: ", end="", flush=True)
                
                # Print the text chunk
                print(data.text, end="", flush=True)
                return response_id
            
        elif isinstance(event, WorkflowOutputEvent):
            # Final output from workflow (non-streaming)
            data = event.data
            if isinstance(data, AgentResponse) and data.text:
                print(f"\n[{event.executor_id}]: {data.text}")
                
        elif isinstance(event, RequestInfoEvent):
            # Workflow needs information (user input)
            if isinstance(event.data, HandoffAgentUserRequest):
                # The agent's streaming response was already printed via AgentRunUpdateEvent
                # Just add a newline before the input prompt
                print()  # Newline after agent output
                
        elif isinstance(event, WorkflowStatusEvent):
            # Status update - only log significant states
            if event.state == WorkflowRunState.IDLE:
                pass  # Workflow completed
            elif event.state == WorkflowRunState.IDLE_WITH_PENDING_REQUESTS:
                pass  # Waiting for user input
        
        return last_response_id
                
    async def cleanup(self) -> None:
        """Clean up resources."""
        if self.provider:
            await self.provider.__aexit__(None, None, None)
        if self.credential:
            await self.credential.close()


async def main():
    """Main entry point."""
    orchestrator = Option1Orchestrator()
    
    try:
        await orchestrator.setup()
        await orchestrator.run_conversation_loop()
    finally:
        await orchestrator.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
