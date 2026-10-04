"""Specialist AI agents that sit on top of the planning pipeline.

- review_analyst: reads real guest reviews and extracts aspect-based sentiment (pros, cons, noise).
- concierge: a ReAct agent that answers traveller questions by planning and calling real MCP tools.
- critic: a self-reflection agent that reviews a finished plan like a travel expert and triggers fixes.

Every agent records its steps in the trip's agent trace (trace.py), and every one has a deterministic
fallback, so the planner keeps working without a model.
"""
