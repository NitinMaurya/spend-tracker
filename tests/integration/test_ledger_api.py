"""The consolidated ledger: every transaction, on every account, with its sign.

All data here is invented. The real database holds a real salary and real
merchants, and none of it belongs in a repository that is public.

What these tests actually defend:

  · The ledger is NOT v_spend. A bank debit, a card repayment, a fee and a
    salary credit all have to appear, or the screen is lying by omission.
  · The sign survives. amount_minor is signed and the ledger never takes an
    absolute value, because that is the only thing separating money arriving
    from money leaving.
  · The totals do not double count. A card payment shows up twice -- once on
    the card, once on the funding account -- so transfer legs are listed but
    kept out of every figure.
  · A transaction type nobody has seen before still works.
"""
import pytest

from analyser import api as api_module
from analyser.db import connect, migrate

# The endpoints are plain functions; calling them directly exercises exactly the
# same code an HTTP request would reach, without adding an HTTP test dependency.


AED = "AED"

#: What the schema's CHECK constraint accepts today. Anything else is a novel type.
KNOWN_TYPES = {"PURCHASE", "REFUND", "PAYMENT", "FEE", "INTEREST", "CASH_ADVANCE",
               "CASH_WITHDRAWAL", "REVERSAL", "ADJUSTMENT", "TRANSFER", "UNKNOWN",
               "SALARY", "INCOME"}

# account_id, issuer, product, type, include_in_spending
ACCOUNTS = [
    ("bank-0001", "TESTBANK", "CURRENT ACCOUNT", "BANK", 0),
    ("card-0002", "TESTBANK", "TEST REWARDS CARD", "CREDIT_CARD", 1),
    ("line-0003", "TESTLINE", None, "CREDIT_FACILITY", 0),
]

# txn_id, account, date, minor (signed), type, merchant, category, transfer, excluded
TXNS = [
    ("t01", "bank-0001", "2026-05-01",  4000000, "SALARY",   "MONTHLY PAY",   None,        None,   0),
    ("t02", "bank-0001", "2026-05-03",  -250000, "PURCHASE", "WIRE OUT",      None,        None,   0),
    ("t03", "bank-0001", "2026-05-09",  -180000, "PAYMENT",  "CARD SETTLE",   None,        "grp1", 0),
    ("t04", "card-0002", "2026-05-09",   180000, "PAYMENT",  "CARD SETTLE",   None,        "grp1", 0),
    ("t05", "card-0002", "2026-05-11",   -12500, "PURCHASE", "CORNER CAFE",   "DINING",    None,   0),
    ("t06", "card-0002", "2026-05-12",    -9900, "FEE",      "ANNUAL FEE",    None,        None,   0),
    ("t07", "card-0002", "2026-05-13",    -4200, "MOONBEAM", "NOVEL TYPE",    None,        None,   0),
    ("t08", "line-0003", "2026-04-20",  -500000, "PURCHASE", "FACILITY DRAW", None,        None,   0),
    ("t09", "card-0002", "2026-04-21",    -3300, "PURCHASE", "STRUCK OUT",    None,        None,   1),
]


@pytest.fixture()
def ledger_db(tmp_path, monkeypatch):
    path = str(tmp_path / "ledger.db")
    conn = connect(path)
    migrate(conn)
    conn.execute("PRAGMA foreign_keys=OFF")

    for account_id, issuer, product, kind, include in ACCOUNTS:
        conn.execute(
            "INSERT INTO accounts (account_id, issuer, product_name, account_type,"
            "                      currency, include_in_spending) VALUES (?,?,?,?,?,?)",
            (account_id, issuer, product, kind, AED, include))

    for i, (tid, account, date, minor, kind, merchant, category, group, excluded) in enumerate(TXNS):
        conn.execute(
            "INSERT INTO transactions_raw (raw_id, document_id, account_id, page_number,"
            "  line_index, raw_text, txn_date, posting_date, raw_description, amount_minor,"
            "  currency) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (tid, "doc-1", account, 1, i, f"{date} {merchant} {minor}", date, date,
             f"{merchant} REF {i:04d}", minor, AED))
        # The schema CHECKs system_txn_type against a known list, so a type the
        # code has never seen arrives the way it really would -- as a user
        # correction, which the view COALESCEs over the system value.
        system_kind = kind if kind in KNOWN_TYPES else "UNKNOWN"
        user_kind = None if kind in KNOWN_TYPES else kind
        conn.execute(
            "INSERT INTO transactions (txn_id, account_id, txn_date, posting_date,"
            "  amount_minor, currency, system_txn_type, user_txn_type, system_merchant,"
            "  system_category, category_confidence, transfer_group_id, excluded)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (tid, account, date, date, minor, AED, system_kind, user_kind, merchant,
             category, "HIGH", group, excluded))
    conn.commit()
    conn.close()

    monkeypatch.setattr(api_module, "DB_PATH", path)
    return path


def get(_db, **params):
    return api_module.ledger(**params)


def ledger_calendar(_db):
    return api_module.ledger_calendar()


def by_id(body):
    return {r["txn_id"]: r for r in body["rows"]}


class TestEverythingIsThere:
    def test_lists_every_transaction_on_every_account(self, ledger_db):
        body = get(ledger_db)
        assert body["page"]["total"] == len(TXNS)
        assert set(by_id(body)) == {t[0] for t in TXNS}

    def test_includes_what_the_spend_view_throws_away(self, ledger_db):
        """The whole point: bank debits, repayments, fees and struck-out rows."""
        rows = by_id(get(ledger_db))
        assert rows["t01"]["txn_type"] == "SALARY"      # bank credit
        assert rows["t02"]["account_type"] == "BANK"    # bank debit, not card spend
        assert rows["t03"]["is_transfer"] is True       # a transfer leg
        assert rows["t06"]["txn_type"] == "FEE"
        assert rows["t09"]["excluded"] == 1             # still listed
        assert rows["t08"]["account_type"] == "CREDIT_FACILITY"

    def test_newest_first(self, ledger_db):
        dates = [r["txn_date"] for r in get(ledger_db)["rows"]]
        assert dates == sorted(dates, reverse=True)


class TestSignsAreLoadBearing:
    def test_amount_keeps_its_sign(self, ledger_db):
        rows = by_id(get(ledger_db))
        assert rows["t01"]["amount"]["minor"] == 4000000
        assert rows["t02"]["amount"]["minor"] == -250000

    def test_direction_follows_the_sign(self, ledger_db):
        rows = by_id(get(ledger_db))
        assert rows["t01"]["direction"] == "IN"
        assert rows["t02"]["direction"] == "OUT"
        for row in get(ledger_db)["rows"]:
            assert row["direction"] == ("OUT" if row["amount"]["minor"] < 0 else "IN")

    def test_money_crosses_the_wire_in_minor_units_with_its_exponent(self, ledger_db):
        amount = by_id(get(ledger_db))["t05"]["amount"]
        assert amount == {"minor": -12500, "currency": AED, "exponent": 2}

    def test_direction_filter(self, ledger_db):
        assert {r["txn_id"] for r in get(ledger_db, direction="in")["rows"]} == {"t01", "t04"}
        out = get(ledger_db, direction="out")
        assert all(r["amount"]["minor"] < 0 for r in out["rows"])
        assert out["page"]["total"] == len(TXNS) - 2


class TestTotalsDoNotDoubleCount:
    def test_transfer_legs_and_struck_rows_are_out_of_the_figures(self, ledger_db):
        totals = get(ledger_db)["totals"]
        assert totals["transfer_legs"] == 2
        assert totals["excluded_rows"] == 1
        assert totals["omitted_rows"] == 3
        assert totals["counted_rows"] == len(TXNS) - 3

    def test_money_in_and_out_are_summed_by_the_engine(self, ledger_db):
        (aed,) = get(ledger_db)["totals"]["by_currency"]
        # t01 only: t04's credit is a transfer leg.
        assert aed["money_in"] == {"minor": 4000000, "currency": AED, "exponent": 2}
        # t02 + t05 + t06 + t07 + t08. Not t03 (transfer), not t09 (struck out).
        assert aed["money_out"]["minor"] == 250000 + 12500 + 9900 + 4200 + 500000
        assert aed["net"]["minor"] == 4000000 - aed["money_out"]["minor"]
        assert aed["in_count"] == 1
        assert aed["out_count"] == 5

    def test_a_naive_sum_of_the_listing_would_be_wrong(self, ledger_db):
        """Guards the actual bug: summing the rows is NOT the reported total."""
        body = get(ledger_db)
        naive = sum(r["amount"]["minor"] for r in body["rows"] if r["amount"]["minor"] > 0)
        assert naive != body["totals"]["by_currency"][0]["money_in"]["minor"]

    def test_the_basis_is_stated(self, ledger_db):
        assert "transfer" in get(ledger_db)["totals"]["basis"].lower()


class TestUnrecognisedTypes:
    def test_a_type_the_code_has_never_seen_still_lists(self, ledger_db):
        rows = by_id(get(ledger_db))
        assert rows["t07"]["txn_type"] == "MOONBEAM"

    def test_it_appears_in_the_type_facet_and_filters(self, ledger_db):
        types = {t["txn_type"]: t["txns"] for t in get(ledger_db)["facets"]["types"]}
        assert types["MOONBEAM"] == 1
        picked = get(ledger_db, txn_type="MOONBEAM")
        assert [r["txn_id"] for r in picked["rows"]] == ["t07"]


class TestScopingAndPaging:
    def test_date_window(self, ledger_db):
        body = get(ledger_db, from_date="2026-05-01", to_date="2026-05-31")
        assert {r["txn_id"] for r in body["rows"]} == {"t01", "t02", "t03", "t04",
                                                      "t05", "t06", "t07"}
        assert body["range"]["first"] == "2026-05-01"
        assert body["range"]["last"] == "2026-05-13"

    def test_account_filter(self, ledger_db):
        body = get(ledger_db, account_id="bank-0001")
        assert {r["account_id"] for r in body["rows"]} == {"bank-0001"}
        assert body["page"]["total"] == 3

    def test_search_covers_the_statement_line(self, ledger_db):
        body = get(ledger_db, q="REF 0004")
        assert [r["txn_id"] for r in body["rows"]] == ["t05"]

    def test_paging_walks_the_whole_ledger_once(self, ledger_db):
        first = get(ledger_db, limit=4, offset=0)
        second = get(ledger_db, limit=4, offset=4)
        third = get(ledger_db, limit=4, offset=8)
        assert first["page"]["has_more"] and second["page"]["has_more"]
        assert third["page"]["has_more"] is False
        seen = [r["txn_id"] for r in first["rows"] + second["rows"] + third["rows"]]
        assert len(seen) == len(set(seen)) == len(TXNS)

    def test_facets_ignore_the_other_filters_so_the_menu_stays_usable(self, ledger_db):
        body = get(ledger_db, account_id="bank-0001")
        assert len(body["facets"]["accounts"]) == len(ACCOUNTS)


class TestLedgerCalendar:
    def test_offers_months_that_hold_no_card_spending_at_all(self, ledger_db):
        body = ledger_calendar(ledger_db)
        months = {m["month"] for y in body["years"] for m in y["months"]}
        assert months == {"2026-04", "2026-05"}

    def test_month_figure_is_money_out_and_omits_transfer_legs(self, ledger_db):
        body = ledger_calendar(ledger_db)
        may = next(m for y in body["years"] for m in y["months"] if m["month"] == "2026-05")
        assert may["spend"]["minor"] == 250000 + 12500 + 9900 + 4200
        assert may["txns"] == 5   # 7 in May, less one transfer leg... and t04's leg


class TestEmptyWindow:
    def test_a_window_with_nothing_in_it_is_not_an_error(self, ledger_db):
        body = get(ledger_db, from_date="2030-01-01", to_date="2030-12-31")
        assert body["page"]["total"] == 0
        assert body["rows"] == []
        assert body["totals"]["by_currency"] == []
        assert body["totals"]["counted_rows"] == 0
