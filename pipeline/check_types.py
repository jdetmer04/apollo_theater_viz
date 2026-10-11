"""Sanity-check LLM act-type batch outputs against red flags from the source data."""
import json, sys
from collections import Counter
from pathlib import Path

B = Path(__file__).resolve().parent.parent / "data" / "enrichment" / "batches"
# well-known acts as a gold mini-set
GOLD = {"lavern-baker": "vocalist", "jimmy-rushing": "vocalist", "lionel-hampton": "band", "lloyd-price": "vocalist",
        "little-willie-john": "vocalist", "count-basie": "band", "ella-fitzgerald": "vocalist", "drifters": "vocal_group",
        "nicholas-brothers": "dance_team", "moms-mabley": "comedian", "butterbeans-and-susie": "comedy_team",
        "soul-stirrers": "gospel", "dinah-washington": "vocalist", "ink-spots": "vocal_group", "bill-robinson": "dancer",
        "redd-foxx": "comedian", "orioles": "vocal_group", "dizzy-gillespie": "band", "ruth-brown": "vocalist"}

def check(n):
    inp = {r["performer_id"]: r for r in json.loads((B / f"types_in_{n}.json").read_text())}
    out_f = B / f"types_out_{n}.json"
    if not out_f.exists():
        return print(n, "missing")
    out = json.loads(out_f.read_text())
    flags = []
    if set(out) != set(inp):
        flags.append(f"id mismatch ({len(set(inp) - set(out))} missing)")
    t = Counter(v["act_type"] for v in out.values())
    conf = Counter(v["confidence"] for v in out.values())
    if t["mc_dj"] > 0.03 * len(out): flags.append(f"mc_dj={t['mc_dj']}")
    freq = [p for p, r in inp.items() if r["n_shows"] >= 5 and p in out]
    low_freq = sum(out[p]["confidence"] == "low" for p in freq)
    if freq and low_freq > 0.25 * len(freq): flags.append(f"low_conf among 5+ show acts={low_freq}/{len(freq)}")
    band_miss = [p for p, r in inp.items() if r["band_billing"] and out.get(p, {}).get("act_type") != "band"]
    gospel_miss = [p for p, r in inp.items() if r["show_types"].get("gospel", 0) >= r["n_shows"] / 2 and out.get(p, {}).get("act_type") != "gospel"]
    gold_miss = [(p, out[p]["act_type"]) for p in inp if p in GOLD and p in out and out[p]["act_type"] != GOLD[p]]
    if len(band_miss) > 3: flags.append(f"band_billing not band: {len(band_miss)}")
    if gospel_miss: flags.append(f"gospel miss: {len(gospel_miss)}")
    if gold_miss: flags.append(f"gold miss: {gold_miss}")
    print(n, "FAIL" if flags else "ok", dict(t.most_common(6)), flags)

for n in (sys.argv[1:] or sorted(p.stem[-2:] for p in B.glob("types_in_*.json"))):
    check(n)
