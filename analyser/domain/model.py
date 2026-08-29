"""Domain types. These encode the decision log; changing them changes a decision."""
from dataclasses import dataclass, field
from typing import Optional, FrozenSet, List

# --- enumerations (plain strings: they cross the SQLite boundary) -------------

class TxnType:
    PURCHASE = "PURCHASE"; REFUND = "REFUND"; PAYMENT = "PAYMENT"
    FEE = "FEE"; INTEREST = "INTEREST"; CASH_ADVANCE = "CASH_ADVANCE"
    CASH_WITHDRAWAL = "CASH_WITHDRAWAL"; REVERSAL = "REVERSAL"
    ADJUSTMENT = "ADJUSTMENT"; TRANSFER = "TRANSFER"; UNKNOWN = "UNKNOWN"
    # Money in that the statement NAMES. Unnamed credits stay UNKNOWN -- guessing
    # what a bare inbound transfer was for is exactly what this engine will not do.
    SALARY = "SALARY"; INCOME = "INCOME"
    # Money that MOVES without being earned or spent, and the two halves of a
    # debt. Keeping these apart is what stops a ledger reporting a wire transfer
    # as a purchase and a loan drawdown as income.
    CHEQUE = "CHEQUE"
    LOAN_DISBURSED = "LOAN_DISBURSED"; LOAN_REPAYMENT = "LOAN_REPAYMENT"
    SPEND = frozenset({PURCHASE, CASH_ADVANCE, CASH_WITHDRAWAL})
    EARNED = frozenset({SALARY, INCOME})
    MOVED = frozenset({TRANSFER, CHEQUE})
    DEBT = frozenset({LOAN_DISBURSED, LOAN_REPAYMENT})


class Confidence:
    HIGH = "HIGH"; MEDIUM = "MEDIUM"; LOW = "LOW"; UNKNOWN = "UNKNOWN"
    ORDER = {UNKNOWN: 0, LOW: 1, MEDIUM: 2, HIGH: 3}


class Routability:
    """D-027: not all spend can move."""
    ROUTABLE = "ROUTABLE"
    MERCHANT_LOCKED = "MERCHANT_LOCKED"
    DIRECT_DEBIT = "DIRECT_DEBIT"
    ACCEPTANCE_LIMITED = "ACCEPTANCE_LIMITED"
    IMMOVABLE = "IMMOVABLE"


class Detectability:
    """D-025: some contractual rules cannot be evaluated from a statement."""
    DETECTABLE = "DETECTABLE"
    CHANNEL_DEPENDENT = "CHANNEL_DEPENDENT"
    UNKNOWABLE = "UNKNOWABLE"


# --- money (D-002 as corrected by D-020a) ------------------------------------

@dataclass(frozen=True)
class Money:
    """Integer minor units + currency + STORED exponent.

    The exponent travels with the value so an ISO 4217 revision can never
    retroactively change what a historical amount meant (D-020a).
    """
    minor: int
    currency: str
    exponent: int = 2

    def __post_init__(self):
        if not isinstance(self.minor, int):
            raise TypeError("Money.minor must be int (no floats -- D-002)")

    def _check(self, other):
        if self.currency != other.currency or self.exponent != other.exponent:
            raise ValueError(f"currency mismatch: {self.currency}/{other.currency}")

    def __add__(self, other):
        self._check(other); return Money(self.minor + other.minor, self.currency, self.exponent)

    def __sub__(self, other):
        self._check(other); return Money(self.minor - other.minor, self.currency, self.exponent)

    def __neg__(self):
        return Money(-self.minor, self.currency, self.exponent)

    def __lt__(self, other):
        self._check(other); return self.minor < other.minor

    def __le__(self, other):
        self._check(other); return self.minor <= other.minor

    @property
    def is_zero(self):
        return self.minor == 0

    @classmethod
    def zero(cls, currency, exponent=2):
        return cls(0, currency, exponent)


# --- transactions -------------------------------------------------------------

@dataclass
class Txn:
    txn_id: str
    account_id: str
    txn_date: str            # ISO-8601
    posting_date: Optional[str]
    amount: Money            # signed: negative = money out
    txn_type: str
    category: Optional[str] = None
    confidence: str = Confidence.UNKNOWN
    routability: str = Routability.ROUTABLE
    merchant: Optional[str] = None
    channel: Optional[str] = None     # D-025: 'BANK_CHANNEL' etc. when known
    excluded: bool = False


# --- card rules ---------------------------------------------------------------

@dataclass(frozen=True)
class CycleSpec:
    """D-012: reward cycles are per-card and keyed on posting date."""
    anchor_day: int = 1               # Mashreq noon: 6 -> cycle runs 6th..5th
    key: str = "POSTING"              # POSTING | TRANSACTION


@dataclass(frozen=True)
class RoundingSpec:
    """D-023: rounding is contractual, never a default."""
    mode: str = "HALF_UP"             # HALF_UP | DOWN | UP
    unit: str = "MINOR"               # MINOR | MAJOR
    scope: str = "CYCLE"              # TXN | CATEGORY | CYCLE


@dataclass(frozen=True)
class Exclusion:
    label: str
    categories: FrozenSet[str] = frozenset()
    txn_types: FrozenSet[str] = frozenset()
    channels: FrozenSet[str] = frozenset()
    detectability: str = Detectability.DETECTABLE
    source_quote: str = ""


@dataclass(frozen=True)
class RewardTier:
    categories: Optional[FrozenSet[str]]   # None = all remaining spend
    rate_bps: int                          # 500 = 5.00%
    cap_per_cycle: Optional[Money] = None
    cap_per_year: Optional[Money] = None
    priority: int = 0                      # lower wins when categories overlap
    valid_from: Optional[str] = None
    valid_to: Optional[str] = None


@dataclass(frozen=True)
class RewardProgram:
    tiers: tuple
    cycle: CycleSpec = CycleSpec()
    rounding: RoundingSpec = RoundingSpec()
    exclusions: tuple = ()
    expiry_months: Optional[int] = None       # D-024
    redemption_channel: Optional[str] = None
    is_cash_equivalent: bool = True
    unit: str = "AED"                         # AED | POINTS | MILES


@dataclass(frozen=True)
class Card:
    card_id: str
    issuer: str
    annual_fee: Money
    reward: RewardProgram
    supplementary_fee: Optional[Money] = None
    fx_fee_bps: Optional[int] = None
    financing_charge_bps: Optional[int] = None
    charge_basis: str = "INTEREST"            # INTEREST | PROFIT | FEE  (D-020g)
    min_spend_per_cycle: Optional[Money] = None
    has_unknowable_exclusion: bool = False     # D-025 -> caps confidence


# --- results ------------------------------------------------------------------

@dataclass(frozen=True)
class AnalysisHorizon:
    """D-016b: value is computed FORWARD over this window."""
    start: str
    months: int = 12


@dataclass
class Cycle:
    start: str
    end: str
    label: str


@dataclass
class RewardLine:
    cycle: str
    category: Optional[str]
    eligible_spend: Money
    rate_bps: int
    gross_reward: Money
    capped_reward: Money
    cap_applied: bool = False
    min_spend_met: bool = True


@dataclass
class RewardResult:
    total: Money
    lines: List[RewardLine] = field(default_factory=list)
    excluded_spend: Optional[Money] = None
    cycles_missing_minimum: int = 0


@dataclass
class Assumption:
    label: str
    value: str
    source: str = "SYSTEM"


@dataclass
class GateFailure:
    gate: str
    detail: str


@dataclass
class ValueResult:
    """Every component exposed separately -- spec §F14 requires a decomposable total."""
    rewards: Money
    annual_fee: Money
    net: Money
    perk_value: Optional[Money] = None
    financing_cost: Optional[Money] = None
    fx_cost: Optional[Money] = None          # None = UNKNOWN, not zero (D-013)
    supplementary_fee: Optional[Money] = None
    assumptions: List["Assumption"] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


@dataclass
class RoutingMove:
    category: str
    from_card: Optional[str]
    to_card: str
    monthly_spend: Money
    annual_gain: Money


@dataclass
class RoutingPlan:
    moves: List[RoutingMove] = field(default_factory=list)
    annual_gain: Optional[Money] = None
    value_unchanged: Optional[Money] = None
    value_if_routed: Optional[Money] = None


@dataclass
class Recommendation:
    verdict: str
    net_annual_value: Money
    confidence: str
    plan: Optional[RoutingPlan] = None
    assumptions: List[Assumption] = field(default_factory=list)
    gate_failures: List[GateFailure] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
