"""Stage 3 helpers: prepare LLM batches, fetch/verify external IDs, merge results.

Enrichment results live in data/enrichment/, one JSON dict per kind keyed by performer_id,
so reruns only touch performers that are missing:
  act_types.json  {pid: {act_type, confidence, source}}        <- Haiku batches
  genres.json     {pid: {genres: [..], confidence, source}}     <- Sonnet batches
  id_candidates.json {pid: {wikidata: [..], musicbrainz: [..]}} <- API search (scripted)
  id_choices.json {pid: {wikidata_qid, mbid, confidence}}       <- Sonnet picks among candidates
  ids.json        {pid: {wikidata_qid, mbid, wikipedia_url, ...}} <- verified by re-fetching

Usage:
  python pipeline/enrich.py prep-types   [--batch 400]
  python pipeline/enrich.py prep-genres  [--min-shows 3 --batch 180]
  python pipeline/enrich.py search-ids   [--min-shows 3]
  python pipeline/enrich.py prep-ids     [--batch 120]
  python pipeline/enrich.py collect <kind>     # merge batch outputs into <kind>.json
  python pipeline/enrich.py verify-ids
"""
import argparse
import json
import time
from collections import Counter, defaultdict
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
INTERIM = ROOT / "data" / "interim"
ENRICH = ROOT / "data" / "enrichment"
BATCHES = ENRICH / "batches"
UA = {"User-Agent": "ApolloTheaterViz/0.1 (personal history research project)"}

ACT_TYPES = ["band", "vocalist", "vocal_group", "instrumentalist", "comedian", "comedy_team", "dancer",
             "dance_team", "novelty", "gospel", "mc_dj", "actor", "other"]
GENRES = ["swing", "big band", "jazz", "bebop", "cool/hard bop", "latin", "calypso", "blues", "jump blues",
          "r&b", "doo-wop", "rock & roll", "soul", "gospel", "pop", "vocal jazz", "boogie-woogie",
          "vaudeville comedy", "tap", "exotic dance", "novelty", "country"]


def load():
    perf = json.load(open(INTERIM / "performers.json"))
    apps = [json.loads(l) for l in open(INTERIM / "appearances_norm.jsonl")]
    shows = {json.loads(l)["show_id"]: json.loads(l) for l in open(INTERIM / "shows.jsonl")}
    return perf, apps, shows


def read(kind):
    f = ENRICH / f"{kind}.json"
    return json.loads(f.read_text()) if f.exists() else {}


def context_rows(perf, apps, shows, ids):
    by_show = defaultdict(list)
    for a in apps:
        by_show[a["show_id"]].append(a)
    shows_of = defaultdict(set)
    for a in apps:
        shows_of[a["performer_id"]].add(a["show_id"])
    names = {p["performer_id"]: p["name"] for p in perf}
    rows = []
    for p in perf:
        pid = p["performer_id"]
        if pid not in ids:
            continue
        sids = shows_of[pid]
        co = Counter(names[a["performer_id"]] for s in sids for a in by_show[s] if a["performer_id"] != pid)
        types = Counter(shows[s]["show_type"] for s in sids)
        hosts = sorted({shows[s]["host"] for s in sids if shows[s]["host"]})
        rows.append({
            "performer_id": pid, "name": p["name"], "billed_as": p["billed_as"],
            "years": f"{p['first_date'][:4]}-{p['last_date'][:4]}", "n_shows": p["n_appearances"],
            "n_headlines": p["n_headlines"], "band_billing": p["is_band_billing"],
            "hints": p["role_hints"] + p["paren_hints"] + ([p["goldberg_note"]] if p.get("goldberg_note") else []),
            "show_types": dict(types), "dj_hosts": hosts, "cobilled_with": [n for n, _ in co.most_common(8)],
        })
    return rows


def write_batches(prefix, rows, size):
    BATCHES.mkdir(parents=True, exist_ok=True)
    for old in BATCHES.glob(f"{prefix}_in_*.json"):
        old.unlink()
    n = 0
    for i in range(0, len(rows), size):
        n += 1
        (BATCHES / f"{prefix}_in_{n:02d}.json").write_text(json.dumps(rows[i:i + size], indent=1))
    print(f"{len(rows)} performers -> {n} {prefix} batches in {BATCHES}")


def prep_types(args):
    perf, apps, shows = load()
    done = read("act_types")
    todo = {p["performer_id"] for p in perf if p["performer_id"] not in done}
    rows = context_rows(perf, apps, shows, todo)
    write_batches("types", rows, args.batch)


def prep_genres(args):
    perf, apps, shows = load()
    done, types = read("genres"), read("act_types")
    todo = {p["performer_id"] for p in perf if p["n_appearances"] >= args.min_shows and p["performer_id"] not in done}
    rows = context_rows(perf, apps, shows, todo)
    for r in rows:
        r["act_type"] = types.get(r["performer_id"], {}).get("act_type")
    write_batches("genres", rows, args.batch)


def wikidata_search(name, tries=4):
    r = requests.get("https://www.wikidata.org/w/api.php", headers=UA, timeout=30, params=dict(
        action="wbsearchentities", search=name, language="en", format="json", limit=5, type="item"))
    if r.status_code == 429 and tries:
        time.sleep(int(r.headers.get("Retry-After", 10)))
        return wikidata_search(name, tries - 1)
    r.raise_for_status()
    return [{"qid": x["id"], "label": x.get("label"), "description": x.get("description")} for x in r.json()["search"]]


def musicbrainz_search(name):
    q = name.replace('"', "")
    r = requests.get("https://musicbrainz.org/ws/2/artist", headers=UA, timeout=30,
                     params=dict(query=f'artist:"{q}"', fmt="json", limit=5))
    if r.status_code == 503:  # rate limited
        time.sleep(3)
        return musicbrainz_search(name)
    r.raise_for_status()
    return [{"mbid": a["id"], "name": a["name"], "type": a.get("type"), "disambiguation": a.get("disambiguation"),
             "country": a.get("country"), "life_span": a.get("life-span"), "score": a.get("score")}
            for a in r.json().get("artists", [])]


def search_ids(args):
    perf, _, _ = load()
    cand = read("id_candidates")
    todo = [p for p in perf if p["n_appearances"] >= args.min_shows and p["performer_id"] not in cand]
    print(f"searching {len(todo)} performers")
    for i, p in enumerate(todo, 1):
        try:
            cand[p["performer_id"]] = {"name": p["name"], "wikidata": wikidata_search(p["name"]),
                                       "musicbrainz": musicbrainz_search(p["name"])}
        except requests.RequestException as e:
            print("  error", p["name"], e)
            continue
        time.sleep(2.0)  # MusicBrainz asks for <= 1 req/sec
        if i % 25 == 0:
            (ENRICH / "id_candidates.json").write_text(json.dumps(cand, indent=1))
            print(f"  {i}/{len(todo)}")
    (ENRICH / "id_candidates.json").write_text(json.dumps(cand, indent=1))


def prep_ids(args):
    perf, apps, shows = load()
    cand, chosen, types = read("id_candidates"), read("id_choices"), read("act_types")
    todo = {pid for pid, c in cand.items() if pid not in chosen and (c["wikidata"] or c["musicbrainz"])}
    rows = context_rows(perf, apps, shows, todo)
    for r in rows:
        r["act_type"] = types.get(r["performer_id"], {}).get("act_type")
        r["wikidata_candidates"] = cand[r["performer_id"]]["wikidata"]
        r["musicbrainz_candidates"] = cand[r["performer_id"]]["musicbrainz"]
        del r["cobilled_with"][5:]
    write_batches("ids", rows, args.batch)


def collect(args):
    kind = {"types": "act_types", "genres": "genres", "ids": "id_choices"}[args.kind]
    merged = read(kind)
    n = 0
    for f in sorted(BATCHES.glob(f"{args.kind}_out_*.json")):
        for pid, v in json.loads(f.read_text()).items():
            merged[pid] = v
            n += 1
    if args.kind == "types":
        bad = {pid: v for pid, v in merged.items() if v.get("act_type") not in ACT_TYPES}
        if bad:
            print("WARNING invalid act_type:", list(bad.items())[:10])
    (ENRICH / f"{kind}.json").write_text(json.dumps(merged, indent=1, sort_keys=True))
    print(f"collected {n} rows -> {kind}.json ({len(merged)} total)")


def get_with_retry(url, params=None, tries=5):
    for _ in range(tries):
        r = requests.get(url, params=params, headers=UA, timeout=30)
        if r.status_code not in (429, 503):
            return r
        time.sleep(int(r.headers.get("Retry-After", 5)))
    return r


def verify_ids(args):
    """Re-fetch every chosen ID; only verified IDs make it into ids.json."""
    chosen, out = read("id_choices"), read("ids")
    todo = [(pid, c) for pid, c in chosen.items() if pid not in out]  # resumable: skip already-verified
    print(f"verifying {len(todo)} of {len(chosen)}")
    for i, (pid, c) in enumerate(todo, 1):
        if i % 25 == 0:
            (ENRICH / "ids.json").write_text(json.dumps(out, indent=1, sort_keys=True))
            print(f"  {i}/{len(todo)}")
        rec = {"confidence": c.get("confidence"), "source": "llm-choice+api-verified"}
        qid, mbid = c.get("wikidata_qid"), c.get("mbid")
        if qid:
            r = get_with_retry(f"https://www.wikidata.org/wiki/Special:EntityData/{qid}.json")
            ents = r.json().get("entities", {}) if r.ok else {}
            if ents:
                qid, ent = next(iter(ents.items()))  # follows redirects if the item was merged since search
                rec["wikidata_qid"] = qid
                rec["wikidata_label"] = ent.get("labels", {}).get("en", {}).get("value")
                site = ent.get("sitelinks", {}).get("enwiki")
                if site:
                    rec["wikipedia_url"] = "https://en.wikipedia.org/wiki/" + site["title"].replace(" ", "_")
                mb_claim = ent.get("claims", {}).get("P434")  # MusicBrainz artist ID
                if mb_claim and not mbid:
                    mbid = mb_claim[0]["mainsnak"].get("datavalue", {}).get("value")
            else:
                print("  unverified QID", pid, qid)
        if mbid:
            time.sleep(1.1)
            r = get_with_retry(f"https://musicbrainz.org/ws/2/artist/{mbid}", params={"fmt": "json"})
            if r.ok:
                rec["mbid"] = mbid
                rec["musicbrainz_name"] = r.json().get("name")
            else:
                print("  unverified MBID", pid, mbid)
        out[pid] = rec
    (ENRICH / "ids.json").write_text(json.dumps(out, indent=1, sort_keys=True))
    print(f"verified {sum(1 for r in out.values() if r.get('wikidata_qid'))} QIDs, "
          f"{sum(1 for r in out.values() if r.get('mbid'))} MBIDs")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("prep-types"); s.add_argument("--batch", type=int, default=400); s.set_defaults(fn=prep_types)
    s = sub.add_parser("prep-genres"); s.add_argument("--min-shows", type=int, default=3)
    s.add_argument("--batch", type=int, default=180); s.set_defaults(fn=prep_genres)
    s = sub.add_parser("search-ids"); s.add_argument("--min-shows", type=int, default=3); s.set_defaults(fn=search_ids)
    s = sub.add_parser("prep-ids"); s.add_argument("--batch", type=int, default=120); s.set_defaults(fn=prep_ids)
    s = sub.add_parser("collect"); s.add_argument("kind", choices=["types", "genres", "ids"]); s.set_defaults(fn=collect)
    s = sub.add_parser("verify-ids"); s.set_defaults(fn=verify_ids)
    args = ap.parse_args()
    ENRICH.mkdir(parents=True, exist_ok=True)
    args.fn(args)


if __name__ == "__main__":
    main()
