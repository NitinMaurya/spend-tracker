"""Canonical issuer registry.

An issuer is a first-class entity, not a string guessed from a file name. It has a
stable id, a display name, the sender domains it mails statements from, and the
parser that reads its documents.

Why this exists: passwords, accounts and statements all need to agree on *who the
bank is*. Deriving that ad hoc from file names produced real bugs -- "Emirates NBD
VISA FLEXI" was treated as a different bank from "Emirates NBD" purely because one
file name was longer.

Resolution order, most reliable first:
  1. the parser that successfully read the document (content-based, definitive)
  2. the sender domain, for documents that cannot be opened yet (encrypted)
  3. UNKNOWN -- never a guess
"""
from dataclasses import dataclass, field
from typing import Optional, Tuple


@dataclass(frozen=True)
class Issuer:
    id: str                       # stable key, used everywhere including the Keychain
    name: str                     # display name
    domains: Tuple[str, ...]      # sender domains that mail statements
    parser: Optional[str] = None  # analyser.parsers key, when one exists
    aliases: Tuple[str, ...] = field(default=())


REGISTRY: Tuple[Issuer, ...] = (
    Issuer("fab", "First Abu Dhabi Bank", ("bankfab.com",), parser="fab",
           aliases=("fab", "first abu dhabi")),
    Issuer("mashreq", "Mashreq", ("mashreq.com", "mashreqbank.com"), parser="mashreq",
           aliases=("mashreq", "noon vip")),
    Issuer("cbd", "Commercial Bank of Dubai", ("cbdstatements.ae", "cbd.ae"),
           parser="cbd", aliases=("cbd", "commercial bank of dubai")),
    Issuer("emirates_islamic", "Emirates Islamic", ("emiratesislamic.ae",),
           parser="emirates_islamic", aliases=("emirates islamic",)),
    Issuer("emirates_nbd", "Emirates NBD", ("emiratesnbd.com",),
           aliases=("emirates nbd", "enbd", "visa flexi")),
    Issuer("wio", "Wio", ("mail.wio.io", "wio.io"), parser="wio", aliases=("wio",)),
    Issuer("dubai_first", "Dubai First", ("dubaifirst.com",), parser="dubai_first",
           aliases=("dubai first",)),
    Issuer("adcb", "ADCB", ("adcb.com",), aliases=("adcb",)),
    Issuer("rakbank", "RAKBANK", ("rakbank.ae",), aliases=("rakbank", "rak bank")),
    Issuer("careem", "Careem", ("careem.com",), aliases=("careem",)),
)

UNKNOWN = Issuer("unknown", "Unknown issuer", ())

_BY_ID = {i.id: i for i in REGISTRY}
_BY_PARSER = {i.parser: i for i in REGISTRY if i.parser}


def by_id(issuer_id) -> Issuer:
    return _BY_ID.get(issuer_id, UNKNOWN)


def by_parser(parser_name) -> Issuer:
    """Definitive: the parser matched the document's own content (D-006)."""
    return _BY_PARSER.get(parser_name, UNKNOWN)


def by_sender(text) -> Issuer:
    """Resolve from a sender domain appearing in `text` (a file name or header).

    Domains are matched with their dots normalised, because downloaded file names
    have punctuation flattened ("statement-emiratesnbd-com"). Matching a REGISTERED
    DOMAIN, rather than any substring, is what stops 'VISA FLEXI' becoming its own
    bank.
    """
    if not text:
        return UNKNOWN
    flat = "".join(ch if ch.isalnum() else "-" for ch in text.lower())

    # Full domain first -- the strongest signal.
    for issuer in REGISTRY:
        for domain in issuer.domains:
            if domain.replace(".", "-") in flat:
                return issuer

    # Then the domain's distinctive label ("emiratesislamic" from
    # "emiratesislamic.ae", "wio" from "mail.wio.io"). Mail systems and file names
    # routinely clip the TLD, so requiring the whole domain would miss real matches.
    # Labels under four characters are skipped as too collision-prone.
    for issuer in REGISTRY:
        for label in (_distinctive_label(d) for d in issuer.domains):
            if label and len(label) >= 4 and label in flat:
                return issuer
    # Fallback: a distinctive alias. Needed for files whose stored name predates the
    # fix that kept sender domains intact, and for a domain that got clipped. Aliases
    # are deliberately distinctive brand words -- never a generic term like "card".
    for issuer in REGISTRY:
        for alias in issuer.aliases:
            if alias.replace(" ", "-") in flat:
                return issuer
    return UNKNOWN


def _distinctive_label(domain):
    """The registrable label: 'bankfab' from 'bankfab.com', 'wio' from 'mail.wio.io'."""
    parts = [p for p in domain.split(".") if p]
    if len(parts) < 2:
        return parts[0] if parts else ""
    return parts[-2]


def resolve(*, parser_name=None, file_name=None) -> Issuer:
    """Best available identification, most reliable source first."""
    if parser_name:
        found = by_parser(parser_name)
        if found is not UNKNOWN:
            return found
    return by_sender(file_name)


def all_issuers():
    return REGISTRY
