#!/usr/bin/env python3
# Copyright (c) Microsoft. All rights reserved.
"""
OPTION2 Main Entry Point

Multi-Agent Absence & Overtime Workflow using Direct Client with Local Tools.

Usage:
    cd OPTION2
    pip install -r requirements.txt
    cp .env.example .env  # Edit with your values
    az login
    python -m src.main

Prerequisites:
    - Azure CLI authenticated (az login)
    - AZURE_OPENAI_ENDPOINT set in .env
    - AZURE_OPENAI_DEPLOYMENT_NAME set in .env (default: gpt-5.2)
"""

import asyncio
import sys
import os

# Add the OPTION2 directory to Python path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.orchestrator import main


if __name__ == "__main__":
    asyncio.run(main())
