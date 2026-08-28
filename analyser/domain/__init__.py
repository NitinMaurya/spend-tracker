"""Domain model and calculation contract.

STUBS ONLY. Every function raises NotImplementedError by design -- the test
suite is written first (D-019) and defines the behaviour these must satisfy.
The dataclasses here ARE the contract; agents implement the functions.
"""
from .model import (  # noqa: F401
    Money, Txn, TxnType, Confidence, Routability, Detectability,
    RewardTier, RewardProgram, CycleSpec, RoundingSpec, Exclusion,
    Card, Cycle, RewardLine, RewardResult, AnalysisHorizon,
    RoutingPlan, RoutingMove, Recommendation, GateFailure, Assumption, ValueResult,
)
from .engine import (  # noqa: F401
    cycles_for, assign_cycle, eligible_spend, compute_rewards,
    apply_rounding, net_value, break_even_spend, sensitivity_bands,
    quality_gates, recommend, route,
)
