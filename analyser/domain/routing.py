"""Spend routing -- the primary output. D-027. Tests: tests/routing/*

The plan answers "what goes on which card, and what stays put". It reallocates
spend that already exists; it never invents any (guardrail G3).

Shape of the solver (D-027):

  * only ROUTABLE purchase spend may move; everything else is pinned,
  * candidate amounts are derived from the *marginal* rate -- a tier's cap and a
    card's minimum spend are the points where the marginal rate changes, so those
    are exactly the amounts worth trying,
  * minimum spends make the objective non-convex, so which minimums to attempt is
    enumerated (2^n over the cards that have one) and the best branch is kept,
  * every candidate allocation is scored by running the real reward engine
    (`compute_rewards`) over the reallocated transactions, so caps, cycles,
    exclusions and rounding are honoured rather than approximated.
"""
from dataclasses import replace
from itertools import combinations

from .model import Money, Routability, RoutingMove, RoutingPlan, TxnType
from .rewards import compute_rewards

_BPS = 10000
_MAX_MIN_CARDS = 8          # 2^n branch enumeration; n is small by construction
_MAX_PASSES = 24


# --- grouping -----------------------------------------------------------------

def _key_month(txn):
    """Coarse bucket for "one cycle's worth" of a group's spend.

    Cards disagree about where a cycle starts (D-012), so the plan is expressed
    per calendar month of the posting date and the exact per-card cycle maths is
    left to `compute_rewards`.
    """
    return (txn.posting_date or txn.txn_date)[:7]


def _is_movable(txn):
    # Only routable purchase-side spend moves. Refunds, payments, fees and
    # anything merchant-locked or on a direct debit stay where they are (D-027.4).
    return (txn.routability == Routability.ROUTABLE
            and txn.txn_type in TxnType.SPEND
            and txn.category is not None)


class _Group:
    """All movable spend of one category currently sitting on one card."""

    def __init__(self, src, category):
        self.src = src
        self.category = category
        self.buckets = {}

    def add(self, txn):
        self.buckets.setdefault(_key_month(txn), []).append(txn)

    @property
    def key(self):
        return (self.src, self.category)

    @property
    def cycles(self):
        return max(len(self.buckets), 1)

    @property
    def total(self):
        return sum(abs(t.amount.minor) for ts in self.buckets.values() for t in ts)

    @property
    def avail(self):
        """Movable spend in a typical cycle."""
        return self.total // self.cycles


def _split(txn, minor, card_id, index):
    """A slice of a transaction, routed to `card_id`. Sign is preserved."""
    sign = -1 if txn.amount.minor < 0 else 1
    amount = Money(sign * minor, txn.amount.currency, txn.amount.exponent)
    return replace(txn, txn_id=f"{txn.txn_id}#{index}", account_id=card_id,
                   amount=amount)


# --- allocation ---------------------------------------------------------------

class _Solver:
    def __init__(self, txns, wallet, horizon):
        self.wallet = list(wallet)
        self.cards = {c.card_id: c for c in self.wallet}
        self.horizon = horizon

        self.fixed = []
        groups = {}
        for t in txns:
            if t.account_id not in self.cards or not _is_movable(t):
                self.fixed.append(t)
                continue
            groups.setdefault((t.account_id, t.category),
                              _Group(t.account_id, t.category)).add(t)
        self.groups = list(groups.values())

        self.months = max(horizon.months, 1)
        self.fixed_spend = {}          # (card_id, category) -> per-cycle minor
        for t in self.fixed:
            if t.account_id in self.cards and t.txn_type in TxnType.SPEND:
                k = (t.account_id, t.category)
                self.fixed_spend[k] = self.fixed_spend.get(k, 0) + abs(t.amount.minor)
        self.fixed_spend = {k: v // self.months for k, v in self.fixed_spend.items()}

        self.currency, self.exponent = self._currency(txns)
        self._cache = {}

    def _currency(self, txns):
        for t in txns:
            return t.amount.currency, t.amount.exponent
        for c in self.wallet:
            return c.annual_fee.currency, c.annual_fee.exponent
        return "AED", 2

    # -- evaluation ------------------------------------------------------------

    def build(self, alloc):
        """Realise an allocation as per-card transaction lists.

        Returns (per_card, moved) where `moved` records what actually moved --
        an allocation can ask for more than a bucket holds, and the plan must
        only ever report spend that exists (G3).
        """
        per_card = {cid: [] for cid in self.cards}
        for t in self.fixed:
            if t.account_id in per_card:
                per_card[t.account_id].append(t)

        moved = {}
        for group in self.groups:
            dests = [(d, a) for d, a in alloc.get(group.key, {}).items() if a > 0]
            for txns in group.buckets.values():
                remaining = {d: a for d, a in dests}
                for t in txns:
                    left = abs(t.amount.minor)
                    index = 0
                    for d, _ in dests:
                        if left <= 0:
                            break
                        take = min(remaining[d], left)
                        if take <= 0:
                            continue
                        remaining[d] -= take
                        left -= take
                        moved[(group.key, d)] = moved.get((group.key, d), 0) + take
                        per_card[d].append(_split(t, take, d, index))
                        index += 1
                    if left <= 0:
                        continue
                    if index == 0:
                        per_card[group.src].append(t)      # untouched
                    else:
                        per_card[group.src].append(_split(t, left, group.src, index))
        return per_card, moved

    def score(self, alloc):
        signature = tuple(sorted(
            (g, d, a) for g, dests in alloc.items() for d, a in dests.items() if a > 0
        ))
        if signature in self._cache:
            return self._cache[signature]
        per_card, _ = self.build(alloc)
        total = 0
        for card in self.wallet:
            total += compute_rewards(per_card[card.card_id], card, self.horizon).total.minor
        self._cache[signature] = total
        return total

    # -- candidate amounts -----------------------------------------------------

    def _dest_spend(self, dest_id, alloc, exclude, categories=None):
        """Per-cycle spend already destined for `dest_id`, ignoring one group."""
        total = 0
        for (cid, category), amount in self.fixed_spend.items():
            if cid != dest_id:
                continue
            if categories is not None and category not in categories:
                continue
            total += amount
        for group in self.groups:
            if group.key == exclude:
                continue
            if categories is not None and group.category not in categories:
                continue
            if group.src == dest_id:
                total += group.avail - sum(alloc.get(group.key, {}).values())
            total += alloc.get(group.key, {}).get(dest_id, 0)
        return total

    def candidates(self, group, dest, alloc):
        """Amounts at which the marginal rate on `dest` changes, plus the extremes."""
        placed = alloc.get(group.key, {})
        room = group.avail - sum(a for d, a in placed.items() if d != dest.card_id)
        if room <= 0:
            return []

        amounts = {0, room}
        for tier in dest.reward.tiers:
            if tier.categories is not None and group.category not in tier.categories:
                continue
            if tier.cap_per_cycle is None or tier.rate_bps <= 0:
                continue
            # Spend at which this tier's per-cycle cap is exactly exhausted: beyond
            # it the marginal rate drops to whatever the next tier pays.
            at_cap = tier.cap_per_cycle.minor * _BPS // tier.rate_bps
            amounts.add(at_cap - self._dest_spend(dest.card_id, alloc, group.key,
                                                  tier.categories))
        if dest.min_spend_per_cycle is not None:
            amounts.add(dest.min_spend_per_cycle.minor
                        - self._dest_spend(dest.card_id, alloc, group.key))

        return sorted({min(max(a, 0), room) for a in amounts})

    # -- search ----------------------------------------------------------------

    def _seed_minimums(self, alloc, dests, attempt):
        """Fill each attempted card up to its minimum before optimising.

        Greedy allocation alone would never take this step: below the threshold
        the card pays nothing, so no single move looks profitable (D-027.3).
        """
        for card in attempt:
            need = card.min_spend_per_cycle.minor - self._dest_spend(card.card_id, alloc, None)
            for group in self.groups:
                if need <= 0:
                    break
                if group.src == card.card_id:
                    continue
                placed = alloc.setdefault(group.key, {})
                room = group.avail - sum(placed.values())
                take = min(room, need)
                if take > 0:
                    placed[card.card_id] = placed.get(card.card_id, 0) + take
                    need -= take

    def _hill_climb(self, alloc, dests):
        best = self.score(alloc)
        for _ in range(_MAX_PASSES):
            improved = False
            for group in self.groups:
                for dest in dests:
                    if dest.card_id == group.src:
                        continue
                    current = alloc.get(group.key, {}).get(dest.card_id, 0)
                    for amount in self.candidates(group, dest, alloc):
                        if amount == current:
                            continue
                        trial = _with(alloc, group.key, dest.card_id, amount)
                        value = self.score(trial)
                        if value > best:
                            best, alloc, current = value, trial, amount
                            improved = True
            if not improved:
                break
        return alloc, best

    def _prune(self, alloc, total):
        """Drop every move that does not pay for itself, cheapest-first."""
        while True:
            entries = [(g, d) for g, dests in alloc.items()
                       for d, a in dests.items() if a > 0]
            worst, worst_gain = None, None
            for key in entries:
                trial = _with(alloc, key[0], key[1], 0)
                gain = total - self.score(trial)
                if gain <= 0 and (worst_gain is None or gain < worst_gain):
                    worst, worst_gain = key, gain
            if worst is None:
                return alloc, total
            alloc = _with(alloc, worst[0], worst[1], 0)
            total = self.score(alloc)

    def solve(self):
        baseline = self.score({})
        min_cards = [c for c in self.wallet if c.min_spend_per_cycle is not None]
        min_cards = min_cards[:_MAX_MIN_CARDS]

        best_alloc, best_total = {}, baseline
        for size in range(len(min_cards) + 1):
            for attempt in combinations(min_cards, size):
                attempted = {c.card_id for c in attempt}
                dests = [c for c in self.wallet
                         if c.min_spend_per_cycle is None or c.card_id in attempted]
                alloc = {}
                self._seed_minimums(alloc, dests, attempt)
                alloc, total = self._hill_climb(alloc, dests)
                alloc, total = self._prune(alloc, total)
                if total > best_total:
                    best_alloc, best_total = alloc, total

        if best_total <= baseline:
            return {}, baseline, baseline
        return best_alloc, baseline, best_total


def _with(alloc, group_key, dest_id, amount):
    """A copy of `alloc` with one (group -> destination) entry set."""
    out = {g: dict(d) for g, d in alloc.items()}
    dests = out.setdefault(group_key, {})
    if amount > 0:
        dests[dest_id] = amount
    else:
        dests.pop(dest_id, None)
    if not dests:
        out.pop(group_key, None)
    return out


# --- public API ---------------------------------------------------------------

def route(txns, wallet, horizon):
    """Build the routing plan: what moves, what stays, and what the move is worth.

    Both incremental figures are reported. Value if nothing changes and value if
    the plan is followed are kept apart deliberately -- collapsing them into one
    number would credit a card with rewards that depend on behaviour the user has
    not yet adopted (D-027.5).
    """
    solver = _Solver(txns, wallet, horizon)
    alloc, unchanged, routed = solver.solve()
    currency, exponent = solver.currency, solver.exponent

    _, moved = solver.build(alloc)
    groups = {g.key: g for g in solver.groups}

    moves = []
    for (group_key, dest_id), amount in moved.items():
        if amount <= 0:
            continue
        group = groups[group_key]
        gain = routed - solver.score(_with(alloc, group_key, dest_id, 0))
        if gain <= 0:                       # never recommend a move that loses money
            continue
        moves.append(RoutingMove(
            category=group.category,
            from_card=group.src,
            to_card=dest_id,
            monthly_spend=Money(amount // group.cycles, currency, exponent),
            annual_gain=Money(gain, currency, exponent),
        ))
    moves.sort(key=lambda m: m.annual_gain.minor, reverse=True)

    value_unchanged = Money(unchanged, currency, exponent)
    value_if_routed = Money(routed, currency, exponent)
    return RoutingPlan(
        moves=moves,
        annual_gain=value_if_routed - value_unchanged,
        value_unchanged=value_unchanged,
        value_if_routed=value_if_routed,
    )
