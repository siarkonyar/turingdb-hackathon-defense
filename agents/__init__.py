"""LLM agents that use TuringDB changes (branches) as their search space.

    threat    finds the disruptions that cost the supply chain the most for the fewest attacks
    defence   tests countermeasures against the worst threat scenario
    scenario  answers natural-language disaster questions with a simulated branch

Every candidate is tried in its own TuringDB change; main is never modified. See docs/agents.md.
"""
