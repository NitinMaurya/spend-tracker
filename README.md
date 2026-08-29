# Spend Tracker

Reads your own credit-card statements, works out where the money actually goes,
and tells you which card to put each kind of spending on.

Everything runs on your machine. Statements are parsed locally, nothing is
uploaded, and no figure on screen was estimated — each one is traceable back to
the line of the PDF it came from.

## Why it is built this way

Financial software that guesses is worse than none, so the engine refuses to.

- **Evidence over inference.** A reward rate is used only if it was quoted
  verbatim in a Key Facts Statement, and only after a human has confirmed which
  spending categories that sentence covers. The extractor will read *"5% cashback
  on dining spends"*; it will not decide what "dining" means for you.
- **Reconciliation is a gate, not a warning.** Extracted transactions are summed
  and compared with the totals the issuer printed. If they disagree, the
  statement is set aside rather than folded quietly into your numbers.
- **Deterministic money.** Every figure is computed once, in Python, in minor
  units with the currency's own exponent. The interface never does arithmetic on
  money — it only displays what the engine returned.
- **Conservative under uncertainty.** Where a rule cannot be evaluated — an
  exclusion that is undetectable from statement text, two sources that disagree —
  the spend is held out of the result instead of assumed in the card's favour.

## Running it

```bash
python -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m analyser.ingest ./statements   # read your PDFs
.venv/bin/python -m analyser.api                   # the local engine, 127.0.0.1:8787

cd ui && npm install && npm run dev                # the interface, localhost:3111
```

Useful command-line entry points:

```bash
python -m analyser review          # the correction queue
python -m analyser rules <card>    # extracted rules, provenance, conflicts
python -m analyser plan            # the routing plan
python -m analyser value <card>    # net value, break-even, sensitivity
```

## The interface

Two destinations, because the tool answers two questions.

- **Money** — what you owe, where it went, and every transaction. Click any
  figure to see the statement line, the parser and version that read it, and
  whether that document reconciled.
- **Plan** — confirm what each card pays, then get the routing plan: which
  categories to move, what each move is worth, and what to leave alone.

`Data` holds the statement library and the fix-up queue.

## Layout

```
analyser/        parsing, normalisation, reward and routing engine
analyser/parsers per-issuer statement readers, written per format
db/migrations/   schema
ui/              Next.js interface
tests/           302 tests
design/          the design system and screen artboards
```

## Notes

Statements, the database, extracted figures and the confirmed wallet all live in
`data/`, which is not tracked. Statement PDF passwords are held in the macOS
Keychain, keyed by issuer — never in a config file, an environment variable, a
log line, or an API response.

Parsers are written per bank format and never guessed at, because a wrong guess
produces plausible but wrong money. A bank with no reader says so instead.
