# Copyright (c) Microsoft. All rights reserved.
"""
Timing Metrics Module for OPTION2

Provides decorators and utilities for measuring execution times across:
- Tool invocations
- Agent responses
- Handoff transitions
- Total workflow duration

Output: Console-formatted timing reports
"""

import time
import functools
import logging
from typing import Callable, Any, Dict, List, Optional
from dataclasses import dataclass, field
from contextlib import contextmanager
from datetime import datetime

logger = logging.getLogger("metrics")


@dataclass
class ToolTiming:
    """Record of a single tool invocation timing."""
    name: str
    start_time: float
    end_time: float
    duration: float
    args: Dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentTiming:
    """Record of agent response timing."""
    name: str
    start_time: float
    end_time: float
    duration: float
    tool_calls: List[ToolTiming] = field(default_factory=list)


@dataclass
class HandoffTiming:
    """Record of handoff transition timing."""
    from_agent: str
    to_agent: str
    start_time: float
    end_time: float
    duration: float


class MetricsCollector:
    """
    Collects and reports timing metrics for the workflow.
    
    Usage:
        metrics = MetricsCollector()
        
        with metrics.track_workflow():
            with metrics.track_agent("router"):
                # agent work
                pass
            
            metrics.record_handoff("router", "absence_agent", 0.234)
        
        metrics.print_report()
    """
    
    def __init__(self):
        self.reset()
    
    def reset(self):
        """Reset all collected metrics."""
        self.workflow_start: Optional[float] = None
        self.workflow_end: Optional[float] = None
        self.tool_timings: List[ToolTiming] = []
        self.agent_timings: List[AgentTiming] = []
        self.handoff_timings: List[HandoffTiming] = []
        self._current_agent: Optional[str] = None
        self._current_agent_start: Optional[float] = None
        self._current_agent_tools: List[ToolTiming] = []
    
    @contextmanager
    def track_workflow(self):
        """Context manager to track total workflow time."""
        self.workflow_start = time.perf_counter()
        try:
            yield
        finally:
            self.workflow_end = time.perf_counter()
    
    @contextmanager
    def track_agent(self, agent_name: str):
        """Context manager to track agent response time."""
        self._current_agent = agent_name
        self._current_agent_start = time.perf_counter()
        self._current_agent_tools = []
        try:
            yield
        finally:
            end_time = time.perf_counter()
            timing = AgentTiming(
                name=agent_name,
                start_time=self._current_agent_start,
                end_time=end_time,
                duration=end_time - self._current_agent_start,
                tool_calls=self._current_agent_tools.copy()
            )
            self.agent_timings.append(timing)
            self._current_agent = None
            self._current_agent_start = None
            self._current_agent_tools = []
    
    def record_tool_call(self, name: str, duration: float, args: Dict[str, Any] = None):
        """Record a tool invocation timing."""
        end_time = time.perf_counter()
        timing = ToolTiming(
            name=name,
            start_time=end_time - duration,
            end_time=end_time,
            duration=duration,
            args=args or {}
        )
        self.tool_timings.append(timing)
        if self._current_agent:
            self._current_agent_tools.append(timing)
    
    def record_handoff(self, from_agent: str, to_agent: str, duration: float):
        """Record a handoff transition timing."""
        end_time = time.perf_counter()
        timing = HandoffTiming(
            from_agent=from_agent,
            to_agent=to_agent,
            start_time=end_time - duration,
            end_time=end_time,
            duration=duration
        )
        self.handoff_timings.append(timing)
    
    @property
    def total_workflow_time(self) -> float:
        """Total workflow duration in seconds."""
        if self.workflow_start and self.workflow_end:
            return self.workflow_end - self.workflow_start
        return 0.0
    
    @property
    def total_tool_time(self) -> float:
        """Sum of all tool execution times."""
        return sum(t.duration for t in self.tool_timings)
    
    @property
    def total_agent_time(self) -> float:
        """Sum of all agent response times."""
        return sum(t.duration for t in self.agent_timings)
    
    @property
    def total_handoff_time(self) -> float:
        """Sum of all handoff transition times."""
        return sum(t.duration for t in self.handoff_timings)
    
    @property
    def network_overhead(self) -> float:
        """Estimated network/API overhead (total - tool execution)."""
        return max(0, self.total_workflow_time - self.total_tool_time)
    
    def print_report(self):
        """Print formatted timing report to console."""
        print("\n")
        print("╔" + "═" * 62 + "╗")
        print("║" + "  OPTION2 TIMING REPORT - Direct Client with Local Tools  ".center(62) + "║")
        print("╠" + "═" * 62 + "╣")
        print(f"║  Total Workflow Time: {self.total_workflow_time:>36.3f}s  ║")
        print("╠" + "═" * 62 + "╣")
        
        # Agent Response Times
        print("║  Agent Response Times:" + " " * 39 + "║")
        for i, timing in enumerate(self.agent_timings):
            prefix = "├─" if i < len(self.agent_timings) - 1 else "└─"
            agent_line = f"  {prefix} {timing.name}"
            print(f"║{agent_line:<48}{timing.duration:>10.3f}s  ║")
        
        print("╠" + "═" * 62 + "╣")
        
        # Tool Execution Times
        print("║  Tool Execution Times:" + " " * 39 + "║")
        if self.tool_timings:
            for i, timing in enumerate(self.tool_timings):
                prefix = "├─" if i < len(self.tool_timings) - 1 else "└─"
                tool_line = f"  {prefix} {timing.name}()"
                print(f"║{tool_line:<48}{timing.duration:>10.3f}s  ║")
        else:
            print("║    (no tool calls recorded)" + " " * 34 + "║")
        
        print("╠" + "═" * 62 + "╣")
        
        # Handoff Transitions
        print("║  Handoff Transitions:" + " " * 40 + "║")
        if self.handoff_timings:
            for i, timing in enumerate(self.handoff_timings):
                prefix = "├─" if i < len(self.handoff_timings) - 1 else "└─"
                handoff_line = f"  {prefix} {timing.from_agent} → {timing.to_agent}"
                print(f"║{handoff_line:<48}{timing.duration:>10.3f}s  ║")
        else:
            print("║    (no handoffs recorded)" + " " * 36 + "║")
        
        print("╠" + "═" * 62 + "╣")
        
        # Summary
        print(f"║  Network/API Overhead: {self.network_overhead:>35.3f}s  ║")
        print(f"║  Tool Calls: {len(self.tool_timings):>47}  ║")
        
        print("╚" + "═" * 62 + "╝")
        print()


# Global metrics collector instance
_metrics = MetricsCollector()


def get_metrics() -> MetricsCollector:
    """Get the global metrics collector instance."""
    return _metrics


def reset_metrics():
    """Reset the global metrics collector."""
    _metrics.reset()


def timed_tool(func: Callable) -> Callable:
    """
    Decorator to automatically time tool execution.
    
    Usage:
        @timed_tool
        @tool
        def my_tool(arg: str) -> str:
            return "result"
    """
    @functools.wraps(func)
    def sync_wrapper(*args, **kwargs):
        start = time.perf_counter()
        try:
            result = func(*args, **kwargs)
            return result
        finally:
            duration = time.perf_counter() - start
            _metrics.record_tool_call(func.__name__, duration, kwargs)
            logger.info(f"⏱️  {func.__name__}() completed in {duration:.3f}s")
    
    @functools.wraps(func)
    async def async_wrapper(*args, **kwargs):
        start = time.perf_counter()
        try:
            result = await func(*args, **kwargs)
            return result
        finally:
            duration = time.perf_counter() - start
            _metrics.record_tool_call(func.__name__, duration, kwargs)
            logger.info(f"⏱️  {func.__name__}() completed in {duration:.3f}s")
    
    import asyncio
    if asyncio.iscoroutinefunction(func):
        return async_wrapper
    return sync_wrapper


def print_timing_header():
    """Print a header for the timing output."""
    print("\n" + "─" * 64)
    print(f"  🕐 Workflow started at {datetime.now().strftime('%H:%M:%S')}")
    print("─" * 64)


def print_tool_call(tool_name: str, duration: float):
    """Print a tool call timing line."""
    print(f"  ⚡ {tool_name}() [{duration:.3f}s]")


def print_agent_response(agent_name: str, duration: float):
    """Print an agent response timing line."""
    print(f"  🤖 [{agent_name}] responded in {duration:.3f}s")


def print_handoff(from_agent: str, to_agent: str, duration: float):
    """Print a handoff timing line."""
    print(f"  🔄 Handoff: {from_agent} → {to_agent} [{duration:.3f}s]")
