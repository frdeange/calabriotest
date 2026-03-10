# Copyright (c) Microsoft. All rights reserved.
"""
OPTION1 Orchestrator - USING THE OFFICIAL FIX

Uses Microsoft Agent Framework with AzureAIProjectAgentProvider (SDK V2) for Azure AI Agent Service.
This version uses the official create_handoff_tools() function from the fix for issue #3713.

NO MORE MONKEY-PATCHING! 🎉
"""

import asyncio
import os
import sys

# Add the agent-framework packages to path
sys.path.insert(0, '/workspaces/calabriotest/agent-framework/python/packages/core')
sys.path.insert(0, '/workspaces/calabriotest/agent-framework/python/packages/orchestrations')
sys.path.insert(0, '/workspaces/calabriotest/agent-framework/python/packages/azure-ai')

from azure.identity.aio import AzureCliCredential
from dotenv import load_dotenv

# Microsoft Agent Framework imports (core)
from agent_framework import (
    AgentResponse,
    AgentResponseUpdate,
    ChatAgent,
    ChatMessage,
    HostedMCPTool,
    WorkflowEvent,
    WorkflowEventType,
    WorkflowRunState,
    tool,
)

# Orchestration imports (HandoffBuilder and helpers)
from agent_framework_orchestrations import (
    HandoffBuilder,
    HandoffAgentUserRequest,
    HandoffSentEvent,
    create_handoff_tools,  # 🆕 The fix!
    get_handoff_tool_name,  # 🆕 Helper function
)

# Azure provider
from agent_framework_azure_ai import AzureAIProjectAgentProvider

from .instructions.absence_instruction import (
    get_absence_agent_instructions,
    get_overtime_agent_instructions,
    get_router_agent_instructions,
)

# Load environment variables
load_dotenv()


class Option1OrchestratorWithFix:
    """
    Orchestrator using Azure AI Agent Service with HandoffBuilder.
    
    🆕 NOW USING THE OFFICIAL FIX FOR ISSUE #3713:
    - Uses create_handoff_tools() to pre-create handoff tools
    - HandoffBuilder automatically skips duplicate tools
    - NO monkey-patching needed!
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
        
        print("🔧 Setting up OPTION1 Orchestrator (WITH OFFICIAL FIX)...")
        print(f"   Project Endpoint: {self.project_endpoint}")
        print(f"   Model: {self.model_deployment}")
        print(f"   MCP Server: {self.mcp_server_url}")
        
        # Create Azure credential
        self.credential = AzureCliCredential()
        
        # Create the agent provider using V2 (Responses API)
        self.provider = AzureAIProjectAgentProvider(credential=self.credential)
        
        # Enter the async context for the provider
        await self.provider.__aenter__()
        
        # Create HostedMCPTool
        mcp_tool = HostedMCPTool(
            name="Microsoft Learn MCP",
            url=self.mcp_server_url,
        )
        
        # ============================================================
        # 🆕 USE THE OFFICIAL create_handoff_tools() FUNCTION!
        # This creates handoff tools that are compatible with Azure AI Agent Service.
        # HandoffBuilder will automatically detect these and skip creating duplicates.
        # ============================================================
        
        print("📦 Creating handoff tools using create_handoff_tools()...")
        
        # Router Agent needs tools to handoff to specialists
        router_handoff_tools = create_handoff_tools(
            target_agent_ids=["AbsenceAgent", "OvertimeAgent"],
            descriptions={
                "AbsenceAgent": "Transfer the conversation to AbsenceAgent for handling time-off, vacation, holiday, sick leave requests",
                "OvertimeAgent": "Transfer the conversation to OvertimeAgent for handling overtime work scheduling requests",
            }
        )
        print(f"   ✅ Created {len(router_handoff_tools)} handoff tools for Router")
        for t in router_handoff_tools:
            print(f"      - {t.name}")
        
        # Specialists need tool to handoff back to router
        specialist_handoff_tools = create_handoff_tools(
            target_agent_ids=["RouterAgent"],
            descriptions={
                "RouterAgent": "Transfer the conversation back to RouterAgent when the current task is complete or user needs different help",
            }
        )
        print(f"   ✅ Created {len(specialist_handoff_tools)} handoff tools for Specialists")
        for t in specialist_handoff_tools:
            print(f"      - {t.name}")
        
        print("")
        print("📦 Creating agents in Azure AI Agent Service...")
        
        # Create Router Agent WITH pre-created handoff tools
        self.router_agent = await self.provider.create_agent(
            name="RouterAgent",
            instructions=get_router_agent_instructions(),
            tools=router_handoff_tools,
        )
        print("   ✅ RouterAgent created")
        
        # Create Absence Agent - temporarily without MCP for testing handoffs
        self.absence_agent = await self.provider.create_agent(
            name="AbsenceAgent",
            instructions=get_absence_agent_instructions(),
            tools=specialist_handoff_tools,
        )
        print("   ✅ AbsenceAgent created")
        
        # Create Overtime Agent - temporarily without MCP for testing handoffs
        self.overtime_agent = await self.provider.create_agent(
            name="OvertimeAgent",
            instructions=get_overtime_agent_instructions(),
            tools=specialist_handoff_tools,
        )
        print("   ✅ OvertimeAgent created")
        
        # ============================================================
        # 🆕 BUILD HANDOFF WORKFLOW - NO MONKEY-PATCHING NEEDED!
        # The HandoffBuilder will automatically detect that our agents
        # already have handoff tools and will skip creating duplicates.
        # ============================================================
        
        print("")
        print("🔗 Configuring HandoffBuilder workflow...")
        print("   🆕 No monkey-patching needed! HandoffBuilder will skip duplicate tools.")
        
        self.workflow = (
            HandoffBuilder(
                name="calabrio_workforce_handoff",
                participants=[self.router_agent, self.absence_agent, self.overtime_agent],
            )
            .with_start_agent(self.router_agent)
            # Define routing relationships (HandoffBuilder will skip duplicate tools)
            .add_handoff(self.router_agent, [self.absence_agent, self.overtime_agent])
            .add_handoff(self.absence_agent, [self.router_agent])
            .add_handoff(self.overtime_agent, [self.router_agent])
            # Custom termination condition
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
        
        print("✅ OPTION1 Orchestrator setup complete (using official fix)!")
        print("")
        
    async def run_conversation_loop(self) -> None:
        """Run an interactive conversation loop using the HandoffBuilder workflow."""
        
        print("=" * 60)
        print("OPTION1: Azure AI Agent Service + MCP with HandoffBuilder")
        print("🆕 Using official fix for issue #3713")
        print("=" * 60)
        print("Type 'exit' or 'quit' to end the conversation.")
        print("-" * 60)
        print("")
        
        if not self.workflow:
            raise RuntimeError("Orchestrator not initialized. Call setup() first.")
        
        # Get initial user input
        user_input = input("You: ").strip()
        if user_input.lower() in ["exit", "quit"]:
            print("\n👋 Goodbye!")
            return
        
        # Track pending request_id for send_responses
        pending_request_id = None
        
        try:
            while True:
                # Print robot emoji at start of agent response
                print("🤖 ", end="", flush=True)
                
                if pending_request_id is None:
                    # First run or after completion - use workflow.run()
                    async for event in self.workflow.run(user_input, stream=True):
                        result = await self._handle_workflow_event(event)
                        if result == "exit":
                            print("\n👋 Goodbye!")
                            return
                        elif isinstance(result, str) and result.startswith("request:"):
                            # Got a request_info event - save the request_id
                            pending_request_id = result.split(":", 1)[1]
                            # Don't break - let the generator complete naturally
                else:
                    # Continue workflow with user response
                    # Create the response using HandoffAgentUserRequest helper
                    response_messages = HandoffAgentUserRequest.create_response(user_input)
                    responses = {pending_request_id: response_messages}
                    pending_request_id = None  # Reset before calling
                    
                    async for event in self.workflow.send_responses_streaming(responses):
                        result = await self._handle_workflow_event(event)
                        if result == "exit":
                            print("\n👋 Goodbye!")
                            return
                        elif isinstance(result, str) and result.startswith("request:"):
                            pending_request_id = result.split(":", 1)[1]
                            # Don't break - let the generator complete naturally
                
                # After agent responds, get next user input
                print("")  # Newline after agent response
                user_input = input("\nYou: ").strip()
                if user_input.lower() in ["exit", "quit"]:
                    print("\n👋 Goodbye!")
                    return
                
        except Exception as e:
            print(f"\n❌ Error during workflow: {e}")
            import traceback
            traceback.print_exc()
            raise
            
    async def _handle_workflow_event(self, event: WorkflowEvent) -> str | None:
        """Handle a workflow event. Returns 'exit', 'request:<id>', or None to continue."""
        
        if event.type == "started":
            # Workflow started - no action needed
            pass
            
        elif event.type == "status":
            # Check workflow state
            if event.state == WorkflowRunState.FAILED:
                error_info = event.details if hasattr(event, 'details') else None
                print(f"\n❌ Workflow failed: {error_info}")
                # Try to get more error details
                if hasattr(event, 'data') and event.data:
                    print(f"   Error data: {event.data}")
                return "exit"
            elif event.state == WorkflowRunState.IDLE:
                # Workflow completed normally - this is fine, continue to get user input
                pass
                
        elif event.type == "handoff_sent":
            # Handoff occurred - event.data is HandoffSentEvent
            if event.data and hasattr(event.data, 'source') and hasattr(event.data, 'target'):
                print(f"\n🔄 Handoff: {event.data.source} → {event.data.target}")
                print("🤖 ", end="", flush=True)  # New agent starts responding
            
        elif event.type == "data":
            # Streaming data from executor
            if isinstance(event.data, AgentResponseUpdate):
                if event.data.text:
                    print(event.data.text, end="", flush=True)
            elif isinstance(event.data, AgentResponse):
                if event.data.text:
                    print(event.data.text, end="", flush=True)
                    
        elif event.type == "executor_failed":
            # An executor (agent) failed
            print(f"\n❌ Executor failed!")
            if hasattr(event, 'details') and event.details:
                print(f"   Details: {event.details}")
            if hasattr(event, 'executor_id'):
                print(f"   Executor: {event.executor_id}")
                
        elif event.type == "request_info":
            # Agent is requesting user input (human-in-the-loop)
            # Return the request_id so caller can use it with send_responses
            if hasattr(event, 'request_id') and event.request_id:
                return f"request:{event.request_id}"
            return "request:default"
            
        elif event.type == "output":
            # Output from executor - streaming tokens
            if event.data:
                if isinstance(event.data, AgentResponseUpdate):
                    if event.data.text:
                        print(event.data.text, end="", flush=True)
                elif isinstance(event.data, AgentResponse):
                    if event.data.text:
                        print(event.data.text, end="", flush=True)
                elif hasattr(event.data, 'text') and event.data.text:
                    print(event.data.text, end="", flush=True)
        
        return None  # Continue processing
                
    async def cleanup(self) -> None:
        """Clean up resources."""
        if self.provider:
            await self.provider.__aexit__(None, None, None)
        if self.credential:
            await self.credential.close()
            

async def main():
    """Main entry point."""
    orchestrator = Option1OrchestratorWithFix()
    
    try:
        await orchestrator.setup()
        await orchestrator.run_conversation_loop()
    except KeyboardInterrupt:
        print("\n\n👋 Interrupted by user")
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await orchestrator.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
