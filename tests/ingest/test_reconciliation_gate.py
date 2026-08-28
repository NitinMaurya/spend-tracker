"""The reconciliation gate — D-004. Extraction is trusted only if it closes."""
import pytest
from analyser.ingest import reconcile, parse_coverage

pytestmark = pytest.mark.red


def summary(**kw):
    base = dict(opening_balance=0, purchases_debits=0, cash_advances=0,
                finance_charges=0, payments_credits=0, total_payment_due=0)
    base.update(kw)
    return base


class TestGate:
    def test_fab_real_totals_reconcile(self):
        """The real FAB statement: debits 1,404.54, credits 565.00, closing 1,402.84."""
        s = summary(opening_balance=56330, purchases_debits=140454,
                    payments_credits=56500, total_payment_due=140284)
        txns = [{"amount_minor": v} for v in (56400, -87019, -100, 100, -20214, -33121)]
        ok, reason = reconcile(s, txns)
        assert ok and reason is None

    def test_missing_transaction_fails_the_gate(self):
        s = summary(purchases_debits=140454, payments_credits=56500)
        txns = [{"amount_minor": v} for v in (56400, -87019, -20214)]   # one row dropped
        ok, _ = reconcile(s, txns)
        assert not ok

    def test_duplicated_transaction_fails_the_gate(self):
        s = summary(purchases_debits=140454, payments_credits=56500)
        txns = [{"amount_minor": v} for v in (56400, -87019, -100, 100, -20214, -33121, -33121)]
        ok, _ = reconcile(s, txns)
        assert not ok

    def test_off_by_one_fil_fails(self):
        """No tolerance: money must be exact."""
        s = summary(purchases_debits=140454, payments_credits=56500)
        txns = [{"amount_minor": v} for v in (56400, -87019, -100, 100, -20214, -33122)]
        assert not reconcile(s, txns)[0]

    def test_zero_transaction_statement_reconciles(self):
        """CBD and Emirates Islamic July 2026 both have no transactions."""
        ok, _ = reconcile(summary(), [])
        assert ok

    def test_failure_reason_is_specific(self):
        s = summary(purchases_debits=140454, payments_credits=56500)
        ok, reason = reconcile(s, [])
        assert not ok and reason and "debit" in reason.lower()


class TestParseCoverage:
    """D-018: prove no content was silently ignored."""

    def test_full_coverage_when_everything_is_classified(self):
        lines = [{"disposition": d} for d in
                 ("HEADER", "TRANSACTION", "TRANSACTION", "SUMMARY", "BOILERPLATE")]
        assert parse_coverage(lines)["unparsed_pct"] == 0

    def test_unparsed_lines_are_reported(self):
        lines = [{"disposition": d} for d in
                 ("HEADER", "TRANSACTION", "UNPARSED", "BOILERPLATE")]
        assert parse_coverage(lines)["unparsed_pct"] > 0

    def test_boilerplate_is_excluded_from_the_denominator(self):
        """A statement that is 90% T&Cs must not read as 90% unparsed."""
        lines = [{"disposition": "BOILERPLATE"}] * 90 + [{"disposition": "TRANSACTION"}] * 10
        assert parse_coverage(lines)["unparsed_pct"] == 0
