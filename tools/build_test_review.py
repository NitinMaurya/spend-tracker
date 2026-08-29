"""Generate a local, self-contained test-review page: test-review.html

Run:  .venv/bin/python tools/build_test_review.py && open test-review.html
Purely local -- nothing is uploaded or published.
"""
import ast, glob, html, json, os, re, subprocess, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)

FILE_META = {
 "test_money.py":                       ("Money representation", "D-002 · D-020a"),
 "test_ids.py":                         ("Deterministic identity", "D-003"),
 "test_fab.py":                         ("FAB parser & reconciliation", "D-004 · D-005 · D-026a"),
 "test_cycles_and_netting.py":          ("Reward cycles & refund netting", "D-012 · D-016a"),
 "test_caps_minimums_rounding.py":      ("Rates, caps, minimums, rounding", "D-011 · D-016 · D-023"),
 "test_expiry_and_redemption.py":       ("Reward expiry & redemption", "D-024 · D-014"),
 "test_transaction_typing.py":          ("Transaction typing", "spec §F2"),
 "test_merchant_and_category.py":       ("Merchant & category", "D-026b · D-026c"),
 "test_reconciliation_gate.py":         ("Reconciliation gate & coverage", "D-004 · D-018"),
 "test_idempotency.py":                 ("Idempotent ingestion", "D-003 · D-018"),
 "test_transfer_matching.py":           ("Transfer matching & identity", "D-007 · D-028c/e"),
 "test_extraction_and_conflicts.py":    ("Terms extraction & conflicts", "D-022 · D-023 · D-028a/h"),
 "test_fx_and_financing.py":            ("FX, financing & instalments", "D-013 · D-020g · D-028b"),
 "test_supplementary_and_horizon.py":   ("Supplementary & horizon", "D-028d · D-016b"),
 "test_exclusions.py":                  ("Exclusions & promotional periods", "D-025 · spec §F8"),
 "test_value_breakeven_sensitivity.py": ("Net value, break-even, sensitivity", "D-010 · D-014 · D-016b · D-024"),
 "test_routing.py":                     ("Spend routing plan", "D-027"),
 "test_gates_and_recommendation.py":    ("Quality gates & verdict", "D-016c/d/e · D-025"),
 "test_critical_failures.py":           ("Adversarial cases", "spec §14 · guardrails G1/G3"),
}
TIER = {
 "tests/unit":        "Foundations",
 "tests/ingest":      "Ingestion",
 "tests/parsers":     "Parsing",
 "tests/normalize":   "Normalization",
 "tests/matching":    "Account matching",
 "tests/rules":       "Card rules",
 "tests/rewards":     "Reward engine",
 "tests/value":       "Valuation",
 "tests/routing":     "Routing",
 "tests/decide":      "Recommendation",
 "tests/adversarial": "Adversarial",
}
TIER_ORDER = list(TIER.values())


def statuses():
    out = subprocess.run([sys.executable, "-m", "pytest", "tests/", "-q", "--tb=no", "-rA"],
                         capture_output=True, text=True).stdout
    st = {}
    for line in out.splitlines():
        m = re.match(r"^(PASSED|FAILED|SKIPPED|ERROR)\s+(\S+)", line)
        if m:
            st[m.group(2)] = m.group(1)
    return st


def collect():
    st = statuses()
    files = []
    for path in sorted(glob.glob("tests/**/*.py", recursive=True)):
        base = os.path.basename(path)
        if base in ("conftest.py", "__init__.py"):
            continue
        tree = ast.parse(open(path).read())
        tier = TIER.get(os.path.dirname(path), "Other")

        def tests_in(node, cls=None):
            items = []
            for n in node.body:
                if isinstance(n, ast.FunctionDef) and n.name.startswith("test"):
                    tid = f"{path}::{cls + '::' if cls else ''}{n.name}"
                    s = st.get(tid)
                    if s is None:
                        hits = [v for k, v in st.items() if k.startswith(tid + "[")]
                        s = "FAILED" if "FAILED" in hits else ("PASSED" if hits else "FAILED")
                    params = sum(1 for k in st if k.startswith(tid + "["))
                    items.append({"name": n.name, "doc": (ast.get_docstring(n) or "").strip(),
                                  "status": s, "id": tid, "params": params, "line": n.lineno})
            return items

        groups = [{"group": n.name, "doc": (ast.get_docstring(n) or "").strip(),
                   "tests": tests_in(n, n.name)}
                  for n in tree.body if isinstance(n, ast.ClassDef)]
        loose = tests_in(tree)
        if loose:
            groups.append({"group": "", "doc": "", "tests": loose})
        title, trace = FILE_META.get(base, (base, ""))
        files.append({"file": path, "base": base, "tier": tier, "title": title,
                      "trace": trace, "doc": (ast.get_docstring(tree) or "").split("\n")[0],
                      "groups": groups})
    files.sort(key=lambda f: (TIER_ORDER.index(f['tier'])
                             if f['tier'] in TIER_ORDER else 99, f['base']))
    return files


def humanise(name):
    s = name[5:] if name.startswith("test_") else name
    return s.replace("_", " ")


def render(files):
    total = sum(len(g["tests"]) for f in files for g in f["groups"])
    passed = sum(1 for f in files for g in f["groups"] for t in g["tests"] if t["status"] == "PASSED")
    cases = sum(max(t["params"], 1) for f in files for g in f["groups"] for t in g["tests"])

    body = []
    for f in files:
        n = sum(len(g["tests"]) for g in f["groups"])
        p = sum(1 for g in f["groups"] for t in g["tests"] if t["status"] == "PASSED")
        body.append(f'''<section class="file" data-tier="{f['tier']}">
  <header class="file-head">
    <div>
      <p class="eyebrow">{html.escape(f['tier'])} · <code>{html.escape(f['file'])}</code></p>
      <h2>{html.escape(f['title'])}</h2>
      <p class="trace">{html.escape(f['trace'])}</p>
    </div>
    <p class="tally"><b>{p}</b> green · <b>{n-p}</b> pending</p>
  </header>''')
        for g in f["groups"]:
            if g["group"]:
                body.append(f'<h3 class="grp">{html.escape(humanise(g["group"]))}</h3>')
                if g["doc"]:
                    body.append(f'<p class="grpdoc">{html.escape(g["doc"])}</p>')
            body.append('<ul class="tests">')
            for t in g["tests"]:
                cls = "ok" if t["status"] == "PASSED" else "pending"
                chip = "green" if t["status"] == "PASSED" else "pending"
                pm = f'<span class="params">×{t["params"]}</span>' if t["params"] > 1 else ""
                doc = f'<p class="doc">{html.escape(t["doc"])}</p>' if t["doc"] else ""
                body.append(f'''<li class="{cls}" data-status="{chip}">
   <label class="seen"><input type="checkbox" data-k="{html.escape(t['id'])}"><span></span></label>
   <div class="tbody">
     <p class="tname">{html.escape(humanise(t['name']))}{pm}</p>
     {doc}
     <p class="loc"><code>{html.escape(t['base'] if 'base' in t else f['base'])}:{t['line']}</code></p>
   </div>
   <span class="chip {chip}">{'green' if chip=='green' else 'pending'}</span>
 </li>''')
            body.append("</ul>")
        body.append(f'''  <label class="note">
    <span>Divergence notes — {html.escape(f['title'])}</span>
    <textarea data-note="{html.escape(f['file'])}" rows="2"
      placeholder="Anything here that does not match how you expect it to work?"></textarea>
  </label>
</section>''')

    return TEMPLATE.replace("{{BODY}}", "\n".join(body)) \
                   .replace("{{TOTAL}}", str(total)).replace("{{PASSED}}", str(passed)) \
                   .replace("{{PENDING}}", str(total - passed)).replace("{{CASES}}", str(cases))


TEMPLATE = r"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Test Review — Spend Tracker</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Serif:wght@500;600&display=swap">
<style>
:root{
  --ink:#1b1d29; --ink-2:#4a4e63; --ink-3:#767a90;
  --bg:#f7f7fa; --card:#ffffff; --line:#e3e3ec; --line-2:#eeeef4;
  --accent:#454a95; --accent-soft:#ecedf8;
  --green:#2c6f52; --green-soft:#e6f1ea;
  --pending:#8a6420; --pending-soft:#f6efe1;
}
@media (prefers-color-scheme:dark){ :root:not([data-theme="light"]){
  --ink:#e8e8f0; --ink-2:#a9adc2; --ink-3:#7b7f95;
  --bg:#131420; --card:#1b1c2a; --line:#2b2d3e; --line-2:#242636;
  --accent:#9ba1ee; --accent-soft:#23253c;
  --green:#7cc4a0; --green-soft:#1a2a24;
  --pending:#d8ad63; --pending-soft:#2c2519;
}}
:root[data-theme="dark"]{
  --ink:#e8e8f0; --ink-2:#a9adc2; --ink-3:#7b7f95;
  --bg:#131420; --card:#1b1c2a; --line:#2b2d3e; --line-2:#242636;
  --accent:#9ba1ee; --accent-soft:#23253c;
  --green:#7cc4a0; --green-soft:#1a2a24;
  --pending:#d8ad63; --pending-soft:#2c2519;
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);
  font:16px/1.6 "IBM Plex Sans",system-ui,-apple-system,sans-serif;
  -webkit-font-smoothing:antialiased}
code{font-family:"IBM Plex Mono",ui-monospace,Menlo,monospace;font-size:.84em}
.wrap{max-width:60rem;margin:0 auto;padding:2.5rem 1.5rem 6rem}
header.top h1{font-family:"IBM Plex Serif",Georgia,serif;font-weight:600;
  font-size:clamp(1.7rem,3.4vw,2.3rem);margin:0 0 .3rem;letter-spacing:-.01em;text-wrap:balance}
header.top p.sub{color:var(--ink-2);margin:0 0 1.6rem;max-width:60ch}
.stats{display:flex;flex-wrap:wrap;gap:.6rem;margin-bottom:1.2rem}
.stat{background:var(--card);border:1px solid var(--line);border-radius:.5rem;
  padding:.6rem .9rem;display:flex;gap:.55rem;align-items:baseline}
.stat b{font-size:1.25rem;font-variant-numeric:tabular-nums;font-weight:600}
.stat span{font-size:.78rem;letter-spacing:.06em;text-transform:uppercase;color:var(--ink-3)}
.stat.g b{color:var(--green)} .stat.p b{color:var(--pending)}
.bar{display:flex;gap:.5rem;flex-wrap:wrap;align-items:center;position:sticky;top:0;z-index:5;
  background:var(--bg);padding:.7rem 0 .8rem;border-bottom:1px solid var(--line);margin-bottom:1.8rem}
.bar input[type=search]{flex:1;min-width:12rem;padding:.45rem .7rem;border-radius:.4rem;
  border:1px solid var(--line);background:var(--card);color:var(--ink);font:inherit;font-size:.9rem}
.bar button{padding:.45rem .8rem;border-radius:.4rem;border:1px solid var(--line);
  background:var(--card);color:var(--ink-2);font:inherit;font-size:.85rem;cursor:pointer}
.bar button[aria-pressed=true]{background:var(--accent-soft);border-color:var(--accent);color:var(--accent);font-weight:500}
.bar button:focus-visible,textarea:focus-visible,input:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
.file{background:var(--card);border:1px solid var(--line);border-radius:.7rem;
  padding:1.3rem 1.4rem;margin-bottom:1.1rem}
.file-head{display:flex;justify-content:space-between;gap:1rem;align-items:flex-start;
  flex-wrap:wrap;border-bottom:1px solid var(--line-2);padding-bottom:.9rem;margin-bottom:.4rem}
.eyebrow{margin:0 0 .25rem;font-size:.74rem;letter-spacing:.07em;text-transform:uppercase;color:var(--ink-3)}
.file-head h2{font-family:"IBM Plex Serif",Georgia,serif;font-size:1.12rem;margin:0;font-weight:600}
.trace{margin:.25rem 0 0;font-size:.8rem;color:var(--accent);font-family:"IBM Plex Mono",monospace}
.tally{margin:0;font-size:.82rem;color:var(--ink-3);white-space:nowrap;font-variant-numeric:tabular-nums}
.tally b{color:var(--ink-2);font-weight:600}
.grp{font-size:.78rem;letter-spacing:.07em;text-transform:uppercase;color:var(--ink-3);
  margin:1.3rem 0 .1rem;font-weight:600;font-family:"IBM Plex Sans",sans-serif}
.grpdoc{margin:.2rem 0 .5rem;font-size:.86rem;color:var(--ink-2);max-width:70ch}
ul.tests{list-style:none;margin:.5rem 0 0;padding:0;display:flex;flex-direction:column;gap:.15rem}
ul.tests li{display:flex;gap:.7rem;align-items:flex-start;padding:.5rem .6rem;border-radius:.4rem}
ul.tests li:hover{background:var(--line-2)}
.tbody{flex:1;min-width:0}
.tname{margin:0;font-size:.93rem;font-weight:500}
.params{font-size:.72rem;color:var(--ink-3);margin-left:.4rem;font-family:"IBM Plex Mono",monospace}
.doc{margin:.2rem 0 0;font-size:.85rem;color:var(--ink-2);max-width:72ch}
.loc{margin:.25rem 0 0;font-size:.74rem;color:var(--ink-3)}
.chip{flex:none;font-size:.7rem;letter-spacing:.05em;text-transform:uppercase;padding:.15rem .5rem;
  border-radius:1rem;font-weight:600;margin-top:.15rem}
.chip.green{background:var(--green-soft);color:var(--green)}
.chip.pending{background:var(--pending-soft);color:var(--pending)}
.seen{flex:none;margin-top:.2rem;cursor:pointer}
.seen input{width:15px;height:15px;accent-color:var(--accent);cursor:pointer}
.note{display:block;margin-top:1.1rem;border-top:1px solid var(--line-2);padding-top:.9rem}
.note span{display:block;font-size:.76rem;letter-spacing:.06em;text-transform:uppercase;
  color:var(--ink-3);margin-bottom:.4rem}
textarea{width:100%;padding:.6rem .7rem;border-radius:.45rem;border:1px solid var(--line);
  background:var(--bg);color:var(--ink);font:inherit;font-size:.9rem;resize:vertical}
.hide{display:none!important}
footer{margin-top:2rem;color:var(--ink-3);font-size:.85rem;text-align:center}
</style></head><body>
<div class="wrap">
<header class="top">
  <h1>Test Review</h1>
  <p class="sub">Every test in the suite, traced to the decision it enforces. Tick tests you have
  read; add a note wherever the behaviour a test asserts is <em>not</em> what you expect. Notes and
  ticks are saved in this browser only.</p>
  <div class="stats">
    <div class="stat"><b>{{TOTAL}}</b><span>tests</span></div>
    <div class="stat"><b>{{CASES}}</b><span>cases</span></div>
    <div class="stat g"><b>{{PASSED}}</b><span>green</span></div>
    <div class="stat p"><b>{{PENDING}}</b><span>pending build</span></div>
  </div>
</header>
<div class="bar">
  <input type="search" id="q" placeholder="Filter tests…" aria-label="Filter tests">
  <button data-f="all" aria-pressed="true">All</button>
  <button data-f="green" aria-pressed="false">Green</button>
  <button data-f="pending" aria-pressed="false">Pending</button>
  <button id="export">Copy notes</button>
</div>
{{BODY}}
<footer>Regenerate with <code>.venv/bin/python tools/build_test_review.py</code></footer>
</div>
<script>
const S={get(k,d){try{return localStorage.getItem(k)??d}catch(e){return d}},
        set(k,v){try{localStorage.setItem(k,v)}catch(e){}}};
document.querySelectorAll('.seen input').forEach(c=>{
  c.checked = S.get('seen:'+c.dataset.k)==='1';
  c.addEventListener('change',()=>S.set('seen:'+c.dataset.k,c.checked?'1':'0'));
});
document.querySelectorAll('textarea[data-note]').forEach(t=>{
  t.value = S.get('note:'+t.dataset.note,'');
  t.addEventListener('input',()=>S.set('note:'+t.dataset.note,t.value));
});
let filter='all';
const apply=()=>{
  const q=(document.getElementById('q').value||'').toLowerCase();
  document.querySelectorAll('ul.tests li').forEach(li=>{
    const okF = filter==='all'||li.dataset.status===filter;
    const okQ = !q||li.textContent.toLowerCase().includes(q);
    li.classList.toggle('hide',!(okF&&okQ));
  });
  document.querySelectorAll('section.file').forEach(s=>{
    s.classList.toggle('hide',!s.querySelector('ul.tests li:not(.hide)'));
  });
};
document.getElementById('q').addEventListener('input',apply);
document.querySelectorAll('.bar button[data-f]').forEach(b=>b.addEventListener('click',()=>{
  filter=b.dataset.f;
  document.querySelectorAll('.bar button[data-f]').forEach(x=>x.setAttribute('aria-pressed',x===b));
  apply();
}));
document.getElementById('export').addEventListener('click',async e=>{
  let out='# Test review notes\n\n';
  document.querySelectorAll('textarea[data-note]').forEach(t=>{
    if(t.value.trim()) out+='## '+t.dataset.note+'\n\n'+t.value.trim()+'\n\n';
  });
  try{ await navigator.clipboard.writeText(out); e.target.textContent='Copied'; }
  catch(err){ console.log(out); e.target.textContent='See console'; }
  setTimeout(()=>e.target.textContent='Copy notes',1600);
});
</script></body></html>"""

if __name__ == "__main__":
    open("test-review.html", "w").write(render(collect()))
    print("wrote test-review.html")
