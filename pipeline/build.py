"""Stage 4: assemble final CSV + JSON exports in data/out/ for D3/Observable."""
import csv
import json
from collections import defaultdict
from itertools import combinations
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INTERIM = ROOT / "data" / "interim"
ENRICH = ROOT / "data" / "enrichment"
OUT = ROOT / "data" / "out"


def read_json(path, default):
    return json.loads(path.read_text()) if path.exists() else default


def write_csv(name, rows, fields):
    with open(OUT / name, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({k: ("|".join(v) if isinstance(v, list) else v) for k, v in r.items()})


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    shows = [json.loads(l) for l in open(INTERIM / "shows.jsonl")]
    apps = [json.loads(l) for l in open(INTERIM / "appearances_norm.jsonl")]
    perf = json.load(open(INTERIM / "performers.json"))
    members = json.load(open(INTERIM / "group_members.json"))
    aliases = json.load(open(INTERIM / "aliases.json"))
    types = read_json(ENRICH / "act_types.json", {})
    genres = read_json(ENRICH / "genres.json", {})
    ids = read_json(ENRICH / "ids.json", {})

    # shows
    for s in shows:
        s["decade"] = f"{s['year'] // 10 * 10}s"
        s["n_acts"] = len({a["performer_id"] for a in apps if a["show_id"] == s["show_id"]})
        s["notes"] = " | ".join(s["notes"])
    show_fields = ["show_id", "date", "week_end", "year", "decade", "show_type", "host", "package_title",
                   "revue_title", "held_over", "duration_days", "date_suspect", "n_acts", "notes", "raw_text", "source_line"]
    write_csv("shows.csv", shows, show_fields)

    # performers
    year_of = {s["show_id"]: s["year"] for s in shows}
    for p in perf:
        pid = p["performer_id"]
        t, g, i = types.get(pid, {}), genres.get(pid, {}), ids.get(pid, {})
        p["act_type"] = p.get("act_type_seed") or t.get("act_type")
        p["act_type_confidence"] = "seed" if p.get("act_type_seed") else t.get("confidence")
        p["genres"] = g.get("genres", [])
        p["genre_confidence"] = g.get("confidence")
        p["is_group"] = p.get("is_group", False) or p["act_type"] in ("vocal_group", "comedy_team", "dance_team", "band")
        p["members"] = members.get(pid, [])
        p["wikidata_qid"], p["mbid"], p["wikipedia_url"] = i.get("wikidata_qid"), i.get("mbid"), i.get("wikipedia_url")
        p["id_confidence"] = i.get("confidence")
    perf_fields = ["performer_id", "name", "real_name", "act_type", "act_type_confidence", "genres", "genre_confidence",
                   "is_group", "members", "first_date", "last_date", "n_appearances", "n_headlines", "billed_as",
                   "role_hints", "wikidata_qid", "mbid", "wikipedia_url", "id_confidence", "goldberg_note"]
    write_csv("performers.csv", perf, perf_fields)

    # appearances
    for a in apps:
        a["is_headliner"] = a["billing_order"] == 1 and not a["featured_of"]
    app_fields = ["show_id", "performer_id", "billing_order", "billed_as", "name_clean", "role_hint", "is_band",
                  "is_headliner", "featured_of", "correction_of", "note"]
    write_csv("appearances.csv", apps, app_fields)
    write_csv("aliases.csv", aliases, ["alias", "performer_id", "source"])
    write_csv("group_members.csv", [{"group_id": g, "member_id": m} for g, ms in members.items() for m in ms],
              ["group_id", "member_id"])

    # co-appearance edges
    by_show = defaultdict(set)
    for a in apps:
        by_show[a["show_id"]].add(a["performer_id"])
    edges = defaultdict(lambda: {"n_shows": 0, "years": []})
    for sid, pids in by_show.items():
        for a, b in combinations(sorted(pids), 2):
            e = edges[(a, b)]
            e["n_shows"] += 1
            e["years"].append(year_of[sid])
    edge_rows = [{"a": a, "b": b, "n_shows": e["n_shows"], "first_year": min(e["years"]), "last_year": max(e["years"])}
                 for (a, b), e in edges.items()]
    edge_rows.sort(key=lambda r: -r["n_shows"])
    write_csv("coappearances.csv", edge_rows, ["a", "b", "n_shows", "first_year", "last_year"])

    # nested bundle for direct D3 loading
    apps_by_show = defaultdict(list)
    for a in apps:
        apps_by_show[a["show_id"]].append({k: a[k] for k in ("performer_id", "billing_order", "billed_as", "role_hint",
                                                             "is_headliner", "featured_of") if a.get(k) not in (None, False)})
    bundle = {
        "meta": {"source": "Marv Goldberg, Apollo Theater Shows (2019)", "n_shows": len(shows), "n_performers": len(perf)},
        "shows": [{**{k: s[k] for k in show_fields if s.get(k) not in (None, "", False)},
                   "acts": sorted(apps_by_show[s["show_id"]], key=lambda a: a["billing_order"])} for s in shows],
        "performers": {p["performer_id"]: {k: p[k] for k in perf_fields if k != "performer_id" and p.get(k) not in (None, [], "", False)}
                       for p in perf},
    }
    (OUT / "apollo.json").write_text(json.dumps(bundle, separators=(",", ":")))
    print(f"wrote {len(shows)} shows, {len(perf)} performers, {len(apps)} appearances, {len(edge_rows)} edges -> {OUT}")


if __name__ == "__main__":
    main()
