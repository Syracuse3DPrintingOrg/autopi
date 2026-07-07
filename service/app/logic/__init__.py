"""A PLC-like, scan-based logic engine.

This package is the pure evaluation core for Phase 2 automation: a
:class:`Rule <.rule.Rule>` pairs a tree of conditions (comparisons, edges,
timers, latches, combined with AND/OR/NOT) with a list of action ids, and an
:class:`Engine <.engine.Engine>` walks its rules once per scan cycle. Time is
always injected (``now``), never read from the wall clock, and there is no
I/O anywhere in this package, so the whole thing is deterministic and cheap to
unit test.

The engine only decides *which* action ids should fire; it does not know
about ``app.actions.registry`` or how an action actually runs. A caller reads
``ScanResult.fire`` and dispatches those ids however it likes (typically
``registry.run(action_id)``), which keeps this package usable outside AutoPi
too.
"""
from .conditions import evaluate_condition
from .engine import Engine, ScanResult
from .rule import Rule

__all__ = ["Rule", "Engine", "ScanResult", "evaluate_condition"]
