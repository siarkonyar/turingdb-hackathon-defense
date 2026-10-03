"""Dover resilience exercises: a deterministic disruption/recovery engine over the isolated `dover` graph.

Exactly three exercises are supported (agents/resilience/exercises.py). Python loads the network, applies the
event, measures every recovery plan and writes the branches; the recovery agent only chooses among prepared,
validated candidates. Rules and assumptions: docs/dover-resilience.md.
"""
