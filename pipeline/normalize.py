"""Stage 2: resolve billed names to canonical performers.

Inputs : data/interim/raw_appearances.jsonl, pipeline/aliases_seed.yaml,
         data/interim/alias_decisions/*.json (LLM adjudications, optional),
         pipeline/aliases_manual.yaml (optional hand overrides)
Outputs: data/interim/performers.json, appearances_norm.jsonl, group_members.json,
         alias_candidates.json (clusters still needing a decision), aliases.json
"""
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

import yaml
from rapidfuzz import fuzz, process

ROOT = Path(__file__).resolve().parent.parent
INTERIM = ROOT / "data" / "interim"
SEED = Path(__file__).resolve().parent / "aliases_seed.yaml"
MANUAL = Path(__file__).resolve().parent / "aliases_manual.yaml"
DECISIONS = INTERIM / "alias_decisions"

NUM_WORDS = {"two": "2", "three": "3", "four": "4", "five": "5", "six": "6", "seven": "7", "eight": "8"}
BAND_SUFFIX = re.compile(
    r"(\s+(&|and)\s+(his|her|their)\s+(ork|orchestra|band)|\s+&\s+(ork|orchestra|band)|\s+(ork|orchestra|band))$", re.I)


def key(name):
    n = name.lower()
    n = re.sub(r'"[^"]*"', " ", n)  # drop quoted nicknames: Marshall "Garbage" Rogers
    n = re.sub(r"\bbros\.?(?=\s|$)", "brothers", n)
    n = n.replace("&", " and ")
    n = re.sub(r"[^a-z0-9 ]", "", n)
    n = re.sub(r"\s+", " ", n).strip()
    n = " ".join(NUM_WORDS.get(w, w) for w in n.split())
    n = re.sub(r"^the ", "", n)
    n = BAND_SUFFIX.sub("", n.replace(" and ", " & ")).replace(" & ", " and ")
    return n.strip()


def is_band_name(name):
    return bool(BAND_SUFFIX.search(name.lower()))


def display_of(name):
    return BAND_SUFFIX.sub("", name.strip(), count=1).strip() if is_band_name(name) else name.strip()


def slug(name):
    return re.sub(r"[^a-z0-9]+", "-", name.lower().replace("&", "and")).strip("-")


class UnionFind:
    def __init__(self):
        self.p = {}

    def find(self, x):
        self.p.setdefault(x, x)
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]
            x = self.p[x]
        return x

    def union(self, a, b, prefer=None):
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return
        # keep the preferred (canonical) root
        if prefer is not None and self.find(prefer) == rb:
            ra, rb = rb, ra
        self.p[rb] = ra


def load_rules():
    """Returns (canonical overrides {root_key: meta}, merges [(canon_name, [variant names], source)], member_aliases)."""
    seed = yaml.safe_load(SEED.read_text())
    merges, meta = [], {}
    for p in seed["performers"]:
        merges.append((p["name"], p.get("aliases", []), "seed"))
        meta[key(p["name"])] = {k: v for k, v in p.items() if k != "aliases"}
    keep_apart, reviewed = [], set()
    for f in sorted(DECISIONS.glob("*.json")) if DECISIONS.exists() else []:
        dec = json.loads(f.read_text())
        for d in dec.get("merge", []):
            merges.append((d["canonical"], d["variants"], "llm"))
        for group in dec.get("keep_separate", []):
            keep_apart += [(a, b) for i, a in enumerate(group) for b in group[i + 1:]]
        reviewed |= {key(n) for n in dec.get("reviewed", [])}
    if MANUAL.exists():
        man = yaml.safe_load(MANUAL.read_text()) or {}
        for d in man.get("merge", []):
            merges.append((d["canonical"], d["variants"], "manual"))
        keep_apart += man.get("keep_separate", [])
    return merges, meta, seed.get("member_aliases", {}), keep_apart, reviewed


def split_members(name, parts):
    if parts:
        return parts
    if re.search(r"\b(brothers|sisters|singers|quartet|trio|band|ork|orchestra|his|her|company|kids|girls|boys)\b", name, re.I):
        return None
    if "&" not in name and "," not in name:
        return None
    return [p.strip() for p in re.split(r",\s*&\s*|,\s*|\s+&\s*|\s+and\s+", name) if p.strip()]


def main():
    apps = [json.loads(l) for l in open(INTERIM / "raw_appearances.jsonl")]
    shows = {json.loads(l)["show_id"]: json.loads(l) for l in open(INTERIM / "shows.jsonl")}
    merges, meta, member_aliases, keep_apart, reviewed = load_rules()

    uf = UnionFind()
    alias_source = {}
    for a in apps:
        uf.find(key(a["name_clean"]))
    for canon, variants, src in merges:
        ck = key(canon)
        uf.find(ck)
        for v in variants:
            vk = key(v)
            if vk and vk != ck:
                uf.union(ck, vk, prefer=ck)
                alias_source[vk] = src
    canon_names = {uf.find(key(c)): c for c, _, _ in merges}

    # group appearances by root key
    by_root = defaultdict(list)
    for a in apps:
        a["root"] = uf.find(key(a["name_clean"]))
        by_root[a["root"]].append(a)

    performers = {}
    for root, rows in by_root.items():
        names = Counter(r["name_clean"] for r in rows)
        plain = Counter({n: c for n, c in names.items() if not is_band_name(n)})
        # prefer a billed spelling without "Ork"/"Band" ("Claude Hopkins" over "Claude Hopkins Ork"),
        # but never strip a suffix that is part of the act's name ("Cowans' Tramp Band")
        display = canon_names.get(root) or (plain or names).most_common(1)[0][0]
        dates = sorted(shows[r["show_id"]]["date"] for r in rows)
        pid = slug(display) or slug(root)
        m = meta.get(root, {})
        performers[root] = {
            "performer_id": pid,
            "name": display,
            "real_name": m.get("real_name"),
            "act_type_seed": m.get("act_type"),
            "goldberg_note": m.get("note"),
            "billed_as": sorted({display_of(n) for n in names} | set(names)),
            "role_hints": sorted({r["role_hint"] for r in rows if r["role_hint"]}),
            "paren_hints": sorted({r["alias_hint"] for r in rows if r["alias_hint"]}),
            "is_band_billing": any(r["is_band"] for r in rows),
            "first_date": dates[0],
            "last_date": dates[-1],
            "n_appearances": len({r["show_id"] for r in rows}),
            "n_headlines": len({r["show_id"] for r in rows if r["billing_order"] == 1 and not r["featured_of"]}),
        }
    # unique ids
    seen = Counter()
    for p in sorted(performers.values(), key=lambda p: -p["n_appearances"]):
        seen[p["performer_id"]] += 1
        if seen[p["performer_id"]] > 1:
            p["performer_id"] += f"-{seen[p['performer_id']]}"

    # group members
    solo_index = {k: p for k, p in performers.items()}
    members = {}
    for root, rows in by_root.items():
        p = performers[root]
        seed_members = meta.get(root, {}).get("members")
        parts = seed_members or split_members(p["name"], next((r["group_parts"] for r in rows if r["group_parts"]), None))
        if not parts:
            continue
        resolved = []
        for part in parts:
            part = re.sub(r"\([^)]*\)", "", part).strip(" ;,.")
            if part not in member_aliases and len(part.split()) < 2:
                continue  # bare surnames/first names ("Ford", "Ross") are too ambiguous to link
            pk = key(member_aliases.get(part, part))
            pk = uf.find(pk) if pk in uf.p else None
            if pk and pk != root and pk in solo_index:
                resolved.append(solo_index[pk]["performer_id"])
        p["is_group"] = True
        if resolved:
            members[p["performer_id"]] = sorted(set(resolved))

    for a in apps:
        a["performer_id"] = performers[a["root"]]["performer_id"]
    remap_enrichment(apps)

    # appearances with performer ids
    with open(INTERIM / "appearances_norm.jsonl", "w") as f:
        for a in apps:
            del a["root"]
            f.write(json.dumps(a) + "\n")
    json.dump(sorted(performers.values(), key=lambda p: p["performer_id"]), open(INTERIM / "performers.json", "w"), indent=1)
    json.dump(members, open(INTERIM / "group_members.json", "w"), indent=1)
    aliases = [{"alias": n, "performer_id": p["performer_id"],
                "source": alias_source.get(key(n), "rule") if key(n) != root else "billed"}
               for root, p in performers.items() for n in p["billed_as"]]
    json.dump(aliases, open(INTERIM / "aliases.json", "w"), indent=1)

    write_candidates(performers, by_root, apps, keep_apart, reviewed)
    print(f"{len(performers)} performers, {len(members)} groups with resolved members")


def remap_enrichment(apps, prev_path=INTERIM / "appearances_norm.jsonl"):
    """If performer ids changed since the last run (renames/merges), carry enrichment results over.
    Old->new mapping is by majority vote over identical appearance rows (show_id + billed_as)."""
    if not prev_path.exists():
        return
    prev = {(a["show_id"], a["billed_as"]): a["performer_id"] for a in map(json.loads, open(prev_path))}
    votes = defaultdict(Counter)
    for a in apps:
        old = prev.get((a["show_id"], a["billed_as"]))
        if old:
            votes[old][a["performer_id"]] += 1
    mapping = {old: c.most_common(1)[0][0] for old, c in votes.items() if c.most_common(1)[0][0] != old}
    if not mapping:
        return
    enrich_dir = ROOT / "data" / "enrichment"
    for f in ["act_types.json", "genres.json", "id_candidates.json", "id_choices.json", "ids.json"]:
        path = enrich_dir / f
        if not path.exists():
            continue
        data = json.loads(path.read_text())
        moved = {mapping.get(k, k): v for k, v in data.items() if k not in mapping}
        for k, v in data.items():  # renamed keys; never clobber an existing result for a merge target
            if k in mapping:
                moved.setdefault(mapping[k], v)
        path.write_text(json.dumps(moved, indent=1, sort_keys=True))
    print(f"remapped {len(mapping)} performer ids in enrichment files")


def write_candidates(performers, by_root, apps, keep_apart, reviewed=frozenset()):
    """Fuzzy near-duplicates (never co-billed) + paren alias hints -> clusters for LLM review."""
    shows_of = {r: {a["show_id"] for a in rows} for r, rows in by_root.items()}
    roots = list(performers)
    names = [performers[r]["name"] for r in roots]
    apart = {frozenset(map(key, pair)) for pair in keep_apart}
    pairs = set()
    scores = process.cdist(names, names, scorer=fuzz.token_sort_ratio, score_cutoff=86, workers=-1)
    for i in range(len(roots)):
        for j in range(i + 1, len(roots)):
            if scores[i][j] and len(roots[i]) > 4 and len(roots[j]) > 4:
                pairs.add((roots[i], roots[j]))
    # one name a word-subset of the other, e.g. "Drifters" / "Original Drifters", "Earl Hines" / "Earl Fatha Hines"
    by_tokens = {r: set(r.split()) for r in roots}
    for i, a in enumerate(roots):
        for b in roots[i + 1:]:
            ta, tb = by_tokens[a], by_tokens[b]
            small, big = (ta, tb) if len(ta) <= len(tb) else (tb, ta)
            if len(small) >= 1 and small < big and len(big) - len(small) == 1 and len(" ".join(small)) >= 6:
                pairs.add((a, b))
    for r, p in performers.items():
        for h in p["paren_hints"]:
            hk = key(h)
            if hk in performers and hk != r:
                pairs.add((r, hk))
    pairs = {(a, b) for a, b in pairs
             if not (shows_of[a] & shows_of[b]) and frozenset((a, b)) not in apart
             and not (a in reviewed and b in reviewed)}

    uf = UnionFind()
    for a, b in pairs:
        uf.union(a, b)
    clusters = defaultdict(set)
    for a, b in pairs:
        clusters[uf.find(a)].update((a, b))
    out = []
    for members in clusters.values():
        out.append([{
            "name": performers[r]["name"],
            "billed_as": performers[r]["billed_as"],
            "years": f"{performers[r]['first_date'][:4]}-{performers[r]['last_date'][:4]}",
            "n": performers[r]["n_appearances"],
            "hints": performers[r]["role_hints"] + performers[r]["paren_hints"],
            "sample_cobills": sample_cobills(r, by_root, apps),
        } for r in sorted(members, key=lambda r: -performers[r]["n_appearances"])])
    out.sort(key=lambda c: -sum(m["n"] for m in c))
    json.dump(out, open(INTERIM / "alias_candidates.json", "w"), indent=1)
    print(f"{len(out)} candidate clusters ({sum(len(c) for c in out)} names)")


def sample_cobills(root, by_root, apps, k=6):
    sids = {a["show_id"] for a in by_root[root]}
    c = Counter(a["name_clean"] for a in apps if a["show_id"] in sids and key(a["name_clean"]) != root)
    return [n for n, _ in c.most_common(k)]


if __name__ == "__main__":
    main()
