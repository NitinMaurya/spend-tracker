"""Inter-account transfer matching — D-007, D-028c."""
import pytest
from analyser.matching import match_transfers, resolve_account

pytestmark = pytest.mark.red


def leg(account, date, amount_minor, desc, tid):
    return {"txn_id": tid, "account_id": account, "posting_date": date,
            "amount_minor": amount_minor, "raw_description": desc}


class TestMatching:
    def test_real_wio_to_fab_pair_matches(self):
        """Wio 'Blu Fab payment -564.00' on 03/07 is FAB's 'PAYMENT RECEIVED 564.00'
        posted 04/07 -- the same money seen from both sides."""
        legs = [leg("wio", "2026-07-03", -56400, "Blu Fab payment", "w1"),
                leg("fab", "2026-07-04", 56400, "PAYMENT RECEIVED - THANK YOU", "f1")]
        groups = match_transfers(legs)
        assert len(groups) == 1
        assert {"w1", "f1"} == set(groups[0]["txn_ids"])

    def test_same_sign_never_matches(self):
        legs = [leg("wio", "2026-07-03", -56400, "x", "a"),
                leg("fab", "2026-07-04", -56400, "y", "b")]
        assert match_transfers(legs) == []

    def test_same_account_never_matches(self):
        legs = [leg("fab", "2026-07-03", -56400, "x", "a"),
                leg("fab", "2026-07-04", 56400, "y", "b")]
        assert match_transfers(legs) == []

    def test_outside_the_day_window_does_not_match(self):
        legs = [leg("wio", "2026-07-03", -56400, "x", "a"),
                leg("fab", "2026-07-20", 56400, "y", "b")]
        assert match_transfers(legs, day_window=5) == []

    def test_inexact_amount_does_not_match(self):
        legs = [leg("wio", "2026-07-03", -56400, "x", "a"),
                leg("fab", "2026-07-04", 56399, "y", "b")]
        assert match_transfers(legs) == []

    def test_ambiguous_candidates_are_flagged_not_auto_matched(self):
        """D-028c: two identical candidate legs must never be silently paired.
        Mis-matching corrupts spend in a way the reconciliation gate cannot catch,
        because both legs reconcile against their own statements."""
        legs = [leg("wio", "2026-07-03", -56400, "x", "a"),
                leg("fab", "2026-07-04", 56400, "y", "b"),
                leg("enbd", "2026-07-04", 56400, "z", "c")]
        groups = match_transfers(legs)
        assert all(g.get("needs_review") for g in groups) or groups == []


class TestAccountIdentity:
    """D-028e: a PAN is an alias, not identity."""

    def test_known_alias_resolves(self):
        aliases = {"4XXX XX** **** NNNN": "fab-blue-signature"}
        assert resolve_account("4XXX XX** **** NNNN", aliases) == "fab-blue-signature"

    def test_reissued_card_with_a_new_alias_maps_to_the_same_account(self):
        aliases = {"4XXX XX** **** NNNN": "fab-blue-signature",
                   "4XXX XX** **** 7745": "fab-blue-signature"}
        assert resolve_account("4XXX XX** **** 7745", aliases) == "fab-blue-signature"

    def test_unknown_pan_returns_none_rather_than_inventing_an_account(self):
        assert resolve_account("9999 99** **** 0000", {}) is None
