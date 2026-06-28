"""
Compatibility exports for system_spec.md ADK import path:

    from google_agents_cli_adk import Agent, Gemini, Tool

Maps spec syntax onto the open-source google-adk runtime.
"""

from __future__ import annotations

from functools import wraps
from typing import Any, Callable, TypeVar

from google.adk.agents.llm_agent import Agent as AdkAgent

F = TypeVar("F", bound=Callable[..., Any])


class Gemini:
    """Model binding object used by the Inner Loop agent specification."""

    def __init__(self, model: str):
        self.model = model


def Tool(func: F) -> F:
    """
    Explicit @Tool decoration from system_spec.md.
    ADK auto-wraps plain callables; this decorator preserves spec semantics.
    """

    @wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        return func(*args, **kwargs)

    wrapper._adk_explicit_tool = True  # type: ignore[attr-defined]
    return wrapper  # type: ignore[return-value]


def Agent(
    *,
    name: str,
    model: Gemini | str,
    instruction: str,
    tools: list | None = None,
    description: str | None = None,
    **kwargs: Any,
) -> AdkAgent:
    """Instantiate an ADK agent using Gemini Enterprise spec constructor shape."""
    model_name = model.model if isinstance(model, Gemini) else model
    return AdkAgent(
        name=name,
        model=model_name,
        instruction=instruction,
        description=description or f"Robo Reliance agent: {name}",
        tools=tools or [],
        **kwargs,
    )


__all__ = ["Agent", "Gemini", "Tool"]
