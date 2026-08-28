"""Re-export surface. Implementations live in per-area modules so that parallel
work does not collide on one file."""
from .cycles import cycles_for, assign_cycle          # noqa: F401
from .rewards import eligible_spend, apply_rounding, compute_rewards  # noqa: F401
from .value import net_value, break_even_spend, sensitivity_bands     # noqa: F401
from .routing import route                            # noqa: F401
from .decide import quality_gates, recommend          # noqa: F401
