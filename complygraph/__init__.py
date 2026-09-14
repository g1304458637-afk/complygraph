"""ComplyGraph — SKU-level market-access compliance engine.

Invariants (enforced in engine + tests):
  * unknown is never pass: a rule with unevaluable applicability can never be
    `verified`, and readiness can never be green while any unknown exists.
  * every evaluation is a deterministic function of
    (product facts, evidence bundle, rule pack versions, market, channel, as_of).
"""

__version__ = "0.1.0"
