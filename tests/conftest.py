"""Shared fixtures. Synthetic by default -- the domain tier needs no real PDFs (D-019)."""
import os
import pytest
from analyser.domain.model import (
    Money, Txn, TxnType, Confidence, Routability, Detectability,
    Card, RewardProgram, RewardTier, CycleSpec, RoundingSpec, Exclusion,
    AnalysisHorizon,
)

AED = "AED"
SAMPLES = os.path.join(os.path.dirname(__file__), "..", "sample_statements")


def aed(major) -> Money:
    """AED from a major-unit number, exact. Accepts str to avoid float literals."""
    from decimal import Decimal
    return Money(int(Decimal(str(major)) * 100), AED, 2)


def txn(date, amount_major, *, category=None, ttype=TxnType.PURCHASE,
        posting=None, confidence=Confidence.HIGH, routability=Routability.ROUTABLE,
        merchant=None, channel=None, account="card-a", tid=None):
    return Txn(
        txn_id=tid or f"{account}:{date}:{amount_major}:{category}:{merchant}",
        account_id=account,
        txn_date=date,
        posting_date=posting or date,
        amount=aed(amount_major),
        txn_type=ttype,
        category=category,
        confidence=confidence,
        routability=routability,
        merchant=merchant,
        channel=channel,
    )


@pytest.fixture
def horizon():
    return AnalysisHorizon(start="2026-01-01", months=12)


@pytest.fixture
def noon_card():
    """Mashreq noon VIP, as extracted from the real KFS + T&C (D-022).

    Rates:   5% noon platforms | 1% other purchases | 0.33% govt/utilities/fuel/telecom
    Fee:     free for life
    Cycle:   posted 6th prev month -> 5th current  (T&C 3.1.4)
    Rounding: T&C says round DOWN to nearest dirham per billing month -- but the
              statement shows 1.83 on 36.57, i.e. HALF_UP. Unresolved conflict (D-023);
              this fixture encodes the STATEMENT behaviour and test_rounding covers both.
    Expiry:  12 months, redeemable only on noon platforms (T&C 4.2/4.3)
    """
    return Card(
        card_id="mashreq-noon-vip",
        issuer="MASHREQ",
        annual_fee=aed(0),
        supplementary_fee=aed(0),
        fx_fee_bps=289,
        financing_charge_bps=4620,
        charge_basis="INTEREST",
        has_unknowable_exclusion=True,   # "any other transactions determined by the Bank"
        reward=RewardProgram(
            unit="AED",
            tiers=(
                RewardTier(categories=frozenset({"NOON"}), rate_bps=500, priority=0),
                RewardTier(
                    categories=frozenset({"GOVERNMENT", "UTILITIES", "EDUCATION",
                                          "CHARITY", "FUEL", "RENT", "TELECOM"}),
                    rate_bps=33, priority=1),
                RewardTier(categories=None, rate_bps=100, priority=2),
            ),
            cycle=CycleSpec(anchor_day=6, key="POSTING"),
            rounding=RoundingSpec(mode="HALF_UP", unit="MINOR", scope="CYCLE"),
            expiry_months=12,
            redemption_channel="NOON_PLATFORM",
            is_cash_equivalent=False,
            exclusions=(
                Exclusion(label="Cash advances", txn_types=frozenset({TxnType.CASH_ADVANCE}),
                          source_quote="Local cash advances"),
                Exclusion(label="Fees and finance charges",
                          txn_types=frozenset({TxnType.FEE, TxnType.INTEREST}),
                          source_quote="All fees charged on the Card by the Bank"),
                Exclusion(label="Merchant reversals", txn_types=frozenset({TxnType.REVERSAL}),
                          source_quote="Transactions reversed by Merchants"),
                Exclusion(label="Utilities paid via bank channels",
                          categories=frozenset({"UTILITIES"}),
                          channels=frozenset({"BANK_CHANNEL"}),
                          detectability=Detectability.CHANNEL_DEPENDENT,
                          source_quote="Utility bill payments ... made through the Bank's "
                                       "payment channels"),
                Exclusion(label="Bank discretion", detectability=Detectability.UNKNOWABLE,
                          source_quote="Any other transactions determined by the Bank "
                                       "from time to time"),
            ),
        ),
    )


@pytest.fixture
def capped_card():
    """Synthetic: 5% groceries capped at AED 100/cycle, AED 5,000/cycle minimum,
    AED 525 annual fee. Exercises spec §Feature 12/13 and §14 example 1."""
    return Card(
        card_id="capped-test",
        issuer="TEST",
        annual_fee=aed(525),
        min_spend_per_cycle=aed(5000),
        reward=RewardProgram(
            tiers=(
                RewardTier(categories=frozenset({"GROCERIES"}), rate_bps=500,
                           cap_per_cycle=aed(100), priority=0),
                RewardTier(categories=None, rate_bps=100, priority=1),
            ),
            cycle=CycleSpec(anchor_day=1, key="POSTING"),
            rounding=RoundingSpec(mode="HALF_UP", unit="MINOR", scope="CYCLE"),
        ),
    )


def require_samples():
    if not os.path.isdir(SAMPLES):
        pytest.skip("sample_statements/ not present (D-026a: PDFs are never committed)")
