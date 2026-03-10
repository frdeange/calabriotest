# Copyright (c) Microsoft. All rights reserved.
"""
OPTION1 Main Entry Point

Launches the orchestrator for Azure AI Agent Service with MCP.
"""

import asyncio
import sys
import os

# Add parent directory to path for module imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.orchestrator_with_fix import main


if __name__ == "__main__":
    print("")
    print("🚀 Starting OPTION1: Azure AI Agent Service + MCP")
    print("")
    asyncio.run(main())
