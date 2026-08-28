"""Mashreq (noon VIP Credit Card) statement parser.

Format notes observed in the sample:
  * Transaction dates print as ``DD/MM`` with **no year** (D-020c). The year is
    inferred from the statement date only -- never from the system clock. If the
    transaction month is *after* the statement month the row belongs to the
    previous calendar year (28/12 on a 06/01/2027 statement is 2026-12-28).
  * A single amount column; card spend is a debit, so it is stored negative.
  * The right-hand Arabic column has no usable ToUnicode map and extracts as
    mojibake; some English extracts reversed ("tnemetats-e"). We read only the
    ASCII band.
  * Summary labels and their figures frequently sit on *different* visual lines
    (the figure is nudged a baseline up or down), so amounts are looked up on
    the label's line first and then on an amount-only neighbouring line.
  * Page 3 carries the per-category cashback table (D-011). Its cycle is the
    reward cycle from the T&C footnote -- 6th of the previous month to the 5th
    of the statement month -- which is *not* the statement cycle (D-012).
"""
import re
import warnings
from decimal import Decimal, ROUND_HALF_UP

warnings.filterwarnings("ignore")
import pdfplumber

PARSER_NAME = "mashreq"
PARSER_VERSION = 1
DATE_FORMAT = "DD/MM"           # transaction rows (year inferred, D-020c)
HEADER_DATE_FORMAT = "DD/MM/YYYY"  # statement / payment-due dates

CURRENCY = "AED"

DDMM = re.compile(r"^(\d{2})/(\d{2})$")
DDMMYYYY = re.compile(r"^(\d{2})/(\d{2})/(\d{4})$")
AMOUNT = re.compile(r"^-?[\d,]+\.\d{2}$")
PERCENT = re.compile(r"^(\d+(?:\.\d+)?)%$")
REFERENCE = re.compile(r"^\d{12,}$")
MASK = re.compile(r"^[Xx*]{4}$")


def infer_year(ddmm, statement_date):
    """Turn a year-less ``DD/MM`` into an ISO date using the statement date.

    The statement date supplies the year. A transaction month *after* the
    statement month cannot belong to the statement's own year, so it wraps back
    one year (a 28/12 row on a 06/01/2027 statement is 2026-12-28). The system
    clock is never consulted (D-020c).
    """
    m = DDMM.match(str(ddmm).strip())
    if not m:
        raise ValueError(f"not a DD/MM date: {ddmm!r}")
    day, month = int(m.group(1)), int(m.group(2))
    s_year, s_month = int(statement_date[0:4]), int(statement_date[5:7])
    year = s_year - 1 if month > s_month else s_year
    return f"{year:04d}-{month:02d}-{day:02d}"


def _reward_cycle(statement_date):
    """T&C 3.1.4: cashback covers postings from the 6th of the previous month
    to the 5th of the statement month."""
    year, month = int(statement_date[0:4]), int(statement_date[5:7])
    p_year, p_month = (year - 1, 12) if month == 1 else (year, month - 1)
    return f"{p_year:04d}-{p_month:02d}-06", f"{year:04d}-{month:02d}-05"


def _ascii(text):
    return "".join(c for c in text if 32 <= ord(c) < 127)


def _lines(page, tol=2.5):
    """Group words into visual lines, dropping non-ASCII (Arabic mojibake)."""
    rows = {}
    for w in page.extract_words(use_text_flow=False, keep_blank_chars=False):
        token = _ascii(w["text"]).strip()
        if not token:
            continue
        rows.setdefault(round(w["top"] / tol), []).append(dict(w, text=token))
    return [sorted(rows[k], key=lambda w: w["x0"]) for k in sorted(rows)]


def _amount_only(words):
    return bool(words) and all(AMOUNT.match(w["text"]) for w in words)


def _amount_for(lines, idx, start=0):
    """The figure belonging to a label on line ``idx``.

    Same line first; otherwise the nearest neighbouring line that is *nothing
    but* an amount -- Mashreq offsets many summary figures by one baseline.
    """
    from analyser.money import to_minor

    for w in lines[idx][start:]:
        if AMOUNT.match(w["text"]):
            return to_minor(w["text"])
    for j in (idx - 1, idx + 1):
        if 0 <= j < len(lines) and _amount_only(lines[j]):
            return to_minor(lines[j][0]["text"])
    return None


def _seq_at(lower, words):
    """Indices where the token sequence ``words`` starts in ``lower``."""
    n = len(words)
    return [i for i in range(len(lower) - n + 1) if lower[i:i + n] == words]


def _detect(pdf):
    head = _ascii(pdf.pages[0].extract_text() or "")
    return "Mashreq" in head or "noon" in head


def parse(path):
    """Return (header, summary, transactions, rewards).

    Amounts are integer fils, signed: negative = money out.
    """
    from analyser.money import to_minor

    header, summary, txns, rewards = {}, {}, [], []
    reward_rows = []

    with pdfplumber.open(path) as pdf:
        if not _detect(pdf):
            raise ValueError("not a Mashreq statement")
        header["page_count"] = len(pdf.pages)

        pages = []
        for pageno, page in enumerate(pdf.pages, start=1):
            lines = _lines(page)
            pages.append((pageno, lines))

            for idx, words in enumerate(lines):
                toks = [w["text"] for w in words]
                lower = [t.lower() for t in toks]

                # --- 'noon VIP Credit Card'
                if "product_name" not in header and len(toks) >= 3 \
                        and lower[-2:] == ["credit", "card"] and "noon" in lower:
                    header["product_name"] = " ".join(toks[lower.index("noon"):])

                # --- 'Card No 4XXX XXXX XXXX NNNN'
                if "masked_number" not in header:
                    for i in range(len(toks) - 3):
                        a, b, c, d = toks[i:i + 4]
                        if a.isdigit() and len(a) == 4 and MASK.match(b) \
                                and MASK.match(c) and d.isdigit() and len(d) == 4:
                            header["masked_number"] = " ".join(toks[i:i + 4])
                            break

                # --- 'Statement date 06/08/2026' (figure may be a line away)
                if "statement_date" not in header:
                    for i in _seq_at(lower, ["statement", "date"]):
                        d = _header_date(lines, idx, i + 2)
                        if d:
                            header["statement_date"] = d
                            break

                # --- 'Payment due date 02/09/2026'
                if "payment_due_date" not in header:
                    for i in _seq_at(lower, ["payment", "due", "date"]):
                        d = _header_date(lines, idx, i + 3)
                        if d:
                            header["payment_due_date"] = d
                            break

                # --- summary block
                for labels, key in (
                    (["previous", "balance"], "opening_balance"),
                    (["new", "transactions"], "purchases_debits"),
                    (["cash", "advance"], "cash_advances"),
                    (["finance", "charges"], "finance_charges"),
                    (["payments"], "payments_credits"),
                    (["outstanding", "balance"], "closing_balance"),
                ):
                    if key in summary:
                        continue
                    hits = _seq_at(lower, labels)
                    if hits:
                        val = _amount_for(lines, idx, hits[0] + len(labels))
                        if val is not None:
                            summary[key] = val
                for i in _seq_at(lower, ["total", "payment"]):
                    if "total_payment_due" not in summary \
                            and i + 2 < len(lower) and lower[i + 2].startswith("due"):
                        val = _amount_for(lines, idx, i + 3)
                        if val is not None:
                            summary["total_payment_due"] = val

                # --- cashback table: '<Category...> 36.57 5% 1.83'
                pct = [j for j, t in enumerate(toks) if PERCENT.match(t)]
                if pct and len(toks) >= 4:
                    j = pct[0]
                    if j >= 2 and AMOUNT.match(toks[j - 1]) and j + 1 < len(toks) \
                            and AMOUNT.match(toks[j + 1]):
                        reward_rows.append({
                            "page_number": pageno,
                            "category_label": " ".join(toks[:j - 1]).strip(),
                            "spend_minor": to_minor(toks[j - 1]),
                            "rate_bps": int((Decimal(PERCENT.match(toks[j]).group(1)) * 100)
                                         .quantize(Decimal("1"), rounding=ROUND_HALF_UP)),
                            "earned": to_minor(toks[j + 1]),
                        })

    statement_date = header.get("statement_date")
    if not statement_date:
        raise ValueError("Mashreq statement date not found; cannot infer transaction years")

    # --- transaction band: '21/07 23/07 noondubai <reference> 36.57'
    for pageno, lines in pages:
        for words in lines:
            toks = [w["text"] for w in words]
            if len(toks) < 4 or not DDMM.match(toks[0]) or not DDMM.match(toks[1]):
                continue
            # Mashreq marks a credit with a bare '-' printed in its own column to
            # the RIGHT of the amount ("925.00  -"); debits end at the amount.
            # Resolve it by geometry -- a '-' inside the description (e.g.
            # "inward ipp cc - ln...") sits far left and must not be mistaken
            # for the sign flag.
            sign_flagged = False
            if toks[-1] == "-" and len(toks) >= 5 and AMOUNT.match(toks[-2]) \
                    and words[-1]["x0"] >= words[-2]["x1"]:
                sign_flagged = True
                toks = toks[:-1]
                words = words[:-1]
            if not AMOUNT.match(toks[-1]):
                raise ValueError(
                    f"Mashreq transaction row not understood: {' '.join(toks)!r}")
            body = toks[2:-1]
            reference = None
            if body and REFERENCE.match(body[-1]):
                reference = body[-1]
                body = body[:-1]
            description = " ".join(body).strip()
            if not description:
                continue
            magnitude = to_minor(toks[-1])
            if magnitude is None:
                continue
            # A credit carries the trailing '-' flag (or a signed/CR amount);
            # everything else on this card is spend.
            is_credit = sign_flagged or magnitude < 0 or toks[-1].upper().endswith("CR")
            txns.append({
                "page_number": pageno,
                "txn_date": infer_year(toks[0], statement_date),
                "posting_date": infer_year(toks[1], statement_date),
                "raw_description": description,
                "currency": CURRENCY,
                "amount_minor": abs(magnitude) if is_credit else -abs(magnitude),
                "reference": reference,
                "raw_text": " ".join(toks),
            })

    cycle_start, cycle_end = _reward_cycle(statement_date)
    for row in reward_rows:
        row["cycle_start"] = cycle_start
        row["cycle_end"] = cycle_end
        rewards.append(row)

    if "total_payment_due" not in summary and "closing_balance" in summary:
        summary["total_payment_due"] = summary["closing_balance"]

    return header, summary, txns, rewards


def _header_date(lines, idx, start):
    """A DD/MM/YYYY date for a header label, on its line or a neighbouring one."""
    for w in lines[idx][start:]:
        m = DDMMYYYY.match(w["text"])
        if m:
            return f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
    label_x0 = lines[idx][start - 1]["x0"] if start else lines[idx][0]["x0"]
    for j in (idx - 1, idx + 1):
        if not (0 <= j < len(lines)):
            continue
        hits = [w for w in lines[j] if DDMMYYYY.match(w["text"])]
        # Geometry, not token counting: the figure sits in the right-hand value
        # column, at or right of the label, and is the first thing on its line.
        # (The rest of such a line is Arabic mojibake, so counting tokens fails.)
        if len(hits) == 1 and hits[0] is lines[j][0] and hits[0]["x0"] >= label_x0:
            m = DDMMYYYY.match(hits[0]["text"])
            return f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
    return None
