"""Stage 1: parse Marv Goldberg's Apollo Theater show list into shows + raw appearances.

Usage: python pipeline/parse.py  (reads uncamarvy.txt, writes data/interim/)
"""
import json
import re
from dataclasses import dataclass, field, asdict
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "uncamarvy.txt"
OUT = ROOT / "data" / "interim"

DATE_RE = re.compile(r"^(\d\d)/(\d\d)/(\d\d)\s+(.*)$")
BAND_RE = re.compile(r"\s+(ork\.?|orchestra|band)$", re.I)
REVUE_RE = re.compile(r"^(.+?)\s+revue$", re.I)
DURATION_RE = re.compile(r"(\d+|six|ten)[- ]days?", re.I)
WORD_NUM = {"six": 6, "ten": 10}

DJ_HOSTS = {
    "dr. jive", "jocko", "alan freed", "hal jackson", "symphony sid", "symphone sid - bop",
    "clay cole", "ralph cooper", "willie bryant", "herman amis", "murray kaufman",
    "jack walker", "evelyn robinson", 'bill "the burner" mercer, wov',
}
CANON_HOST = {"symphone sid - bop": "Symphony Sid", 'bill "the burner" mercer, wov': 'Bill "The Burner" Mercer'}

ROLE_HINTS = {
    "dancer", "dancers", "tap dancer", "young dancers", "fan dancer", "comedian", "contortionist",
    "magician", "magic", "mc", "dj", "singer", "singers", "trumpeter", "sax", "bass", "juggler",
    "ventriloquist", "hypnotist", "ice skater", "musical acrobats", "singing cowboy", "blind pianist",
    "underwater stripper", "girl baritone", "a fighter", "calypso", "all-girl band", "all-girl ork",
    "south american band", "the human ape", "dances on a xylophone", "amateur show winners",
    "musical comedy", "musical revue", "stripper", "mixed group; would be with arthur godfrey",
}
KNOWN_COMMA_ACTS = ["Lambert, Hendricks & Ross"]
PRODUCTION_HINTS = {"musical comedy", "musical revue"}


@dataclass
class Show:
    show_id: str
    date: str
    week_end: str
    year: int
    source_line: int
    raw_text: str
    show_type: str = "regular"
    host: str | None = None
    package_title: str | None = None
    revue_title: str | None = None
    held_over: bool = False
    duration_days: int | None = None
    date_suspect: bool = False
    notes: list = field(default_factory=list)


@dataclass
class Appearance:
    show_id: str
    billing_order: int
    billed_as: str
    name_clean: str
    role_hint: str | None = None
    is_band: bool = False
    featured_of: str | None = None
    correction_of: str | None = None
    alias_hint: str | None = None
    note: str | None = None
    group_parts: list | None = None
    source_line: int = 0


def split_depth0(s, sep):
    """Split on `sep` only outside () and []."""
    out, buf, depth = [], [], 0
    for c in s:
        if c in "([":
            depth += 1
        elif c in ")]":
            depth = max(0, depth - 1)
        if c == sep and depth == 0:
            out.append("".join(buf))
            buf = []
        else:
            buf.append(c)
    out.append("".join(buf))
    return [x.strip() for x in out if x.strip()]


def merge_trios(tokens):
    """'Ford, Bowie, & Bennie' tokenizes as [Ford, Bowie, & Bennie]; glue back into one act.
    Every occurrence in the source is a trio, so merge exactly the two preceding tokens."""
    out = []
    for t in tokens:
        if t.startswith("& ") and len(out) >= 2:
            parts = [out[-2], out[-1], t[2:].strip()]
            out = out[:-2] + [{"text": f"{parts[0]}, {parts[1]}, & {parts[2]}", "parts": parts}]
        else:
            out.append(t)
    return [o if isinstance(o, dict) else {"text": o, "parts": None} for o in out]


def tokenize(body):
    body = re.sub(r"\b(Ork)\. (?=[A-Z])", r"\1, ", body)  # "Cootie Williams Ork. Foxx & White" (missing comma)
    for name in KNOWN_COMMA_ACTS:  # acts whose own name contains a comma but no Oxford-comma "&"
        body = body.replace(name, name.replace(",", ""))
    if body.count(";") >= 2 and len(split_depth0(body, ";")) >= 3:
        tokens = []
        for seg in split_depth0(body, ";"):
            # within a ;-segment, '&' means one act (e.g. "Sandy, Apus & George")
            if "&" in seg:
                tokens.append(seg)
            else:
                tokens.extend(split_depth0(seg, ","))
        return merge_trios(tokens)
    return merge_trios(split_depth0(body, ","))


def classify_show_bracket(show, inner):
    """Apply a leading [..] label to the show. Returns leftover text, if any, to treat as a note."""
    low = inner.lower().strip().lstrip("[")
    m = DURATION_RE.search(low)
    if m:
        n = m.group(1).lower()
        show.duration_days = WORD_NUM.get(n) or int(n)
    if "held over" in low:
        show.held_over = True
    if low.startswith("closed"):
        show.show_type = "closed"
        show.notes.append(inner)
    elif "either closed or movie" in low:
        show.show_type = "closed"
        show.notes.append(inner)
    elif low.startswith("movie"):
        show.show_type = "movie"
        show.notes.append(inner)
    elif "started wednesday - movie" in low:
        show.show_type = "movie"
        show.notes.append(inner)
    elif low.startswith("play") or "- play" in low:
        show.show_type = "play"
        show.notes.append(inner)
    elif low.startswith("legitimate theater"):
        show.show_type = "legit"
    elif low.startswith("gospel"):
        show.show_type = "gospel"
    elif low.startswith("jewel box revue"):
        show.show_type = "jewel_box"
        show.package_title = "Jewel Box Revue"
    elif low.startswith("dr. jive"):
        show.host = "Dr. Jive"
    elif low in DJ_HOSTS:
        show.host = CANON_HOST.get(low, inner.strip().lstrip("["))
    elif low == "held over":
        pass
    elif m and re.match(r"^[a-z].*revue - \d+ days$", low):  # [Motortown Revue - 10 days]
        show.package_title = inner.split(" - ")[0].strip()
    elif m or low.startswith("started") or low.startswith("ran ") or low.startswith("supposedly") or low.startswith("note"):
        show.notes.append(inner)
    else:
        show.package_title = inner.strip().lstrip("[")
        if "(wov)" in low:  # [Evelyn Robinson (WOV) R&B Revue]
            show.host = "Evelyn Robinson"
    if show.host and show.show_type == "regular":
        show.show_type = "dj_revue"


def parse_paren(inner):
    """Classify a per-act (...) annotation."""
    low = inner.lower().strip()
    if low.startswith("with "):
        names = re.split(r"\s+(?:and|&)\s+", inner[5:].strip())
        return {"featured": [n.strip() for n in names if n.strip()]}
    if low.startswith("s/b "):
        return {"correction": inner[4:].strip()}
    if low in ROLE_HINTS:
        return {"role": low}
    # short capitalized names are identity/alias hints: (Billie Holiday), (T-Bone), (Spo-Dee-O-Dee)
    stripped = inner.strip().strip('"')
    if (len(stripped.split()) <= 3 and stripped[:1].isupper() and not re.search(r"\b(only|in ad|was|is|still)\b", low)):
        return {"alias": stripped}
    return {"note": inner.strip()}


def clean_name(text):
    """Strip parentheticals, collapse editorial [inserts] into the name, normalize spaces."""
    t = re.sub(r"\([^)]*\)", "", text)
    t = re.sub(r"\[([^\]]*)\]", lambda m: "" if " " in m.group(1) and "," in m.group(1) else m.group(1), t)
    t = t.replace("[", "").replace("]", "")
    t = re.sub(r"\s+", " ", t).strip().rstrip(",;").strip()
    t = re.sub(r"^(and|the|plus)\s+", "", t)
    t = re.sub(r"\bOrk\.$", "Ork", t, flags=re.I)
    return t


def parse_act(text, show, order, line_no, parts=None):
    """Returns list of Appearance (main act + any featured performers)."""
    apps = []
    parens = re.findall(r"\(([^)]*)\)", text)
    brackets_notes = [b for b in re.findall(r"\[([^\]]*)\]", text) if "," in b and " " in b]
    name = clean_name(text)
    if not name:
        return apps
    app = Appearance(show.show_id, order, text.strip(), name, source_line=line_no, group_parts=parts)
    featured = []
    for p in parens:
        info = parse_paren(p)
        if "role" in info:
            app.role_hint = info["role"]
        elif "featured" in info:
            featured.extend(info["featured"])
        elif "correction" in info:
            app.correction_of = name
            app.name_clean = info["correction"]
        elif "alias" in info:
            app.alias_hint = info["alias"]
        else:
            app.note = "; ".join(filter(None, [app.note, info["note"]]))
    if brackets_notes:
        app.note = "; ".join(filter(None, [app.note] + brackets_notes))
    m = re.match(r"^(.+?)\s+-\s+(.+)$", app.name_clean)
    if m:  # "Major Bowes Colored Stars Revue - Earl Scott & Leslie Waters", "Tropicana (musical comedy) - Rosetta Tharpe"
        show.revue_title = show.revue_title or re.sub(r"\s+(musical comedy|revue)$", "", m.group(1), flags=re.I)
        app.name_clean = m.group(2)
        app.role_hint = None if app.role_hint in PRODUCTION_HINTS else app.role_hint
    if app.role_hint in PRODUCTION_HINTS:
        show.revue_title = show.revue_title or app.name_clean
        return []
    elif re.search(r'^[^"]*"[^"]+"$', app.name_clean) and not re.search(r'\w+ "\w+"\s', app.name_clean):
        # quoted production titles: "Inside Harlem", Clarence Robinson's "Tropicana Revue", "Tobacco Road"
        show.revue_title = show.revue_title or app.name_clean.split('"')[1]
        return apps
    m = REVUE_RE.match(app.name_clean)
    if m and not re.search(r"\b(ork|band)\b", app.name_clean, re.I):
        show.revue_title = show.revue_title or m.group(1)
        for f in featured:  # "Harlem Showboat revue (with X)" — keep the featured act
            apps.append(Appearance(show.show_id, order, f, f, featured_of=None, source_line=line_no))
        return apps
    if BAND_RE.search(app.name_clean) or re.search(r"\b(and|&) his (band|ork|orchestra)\b", app.name_clean, re.I) or (app.role_hint or "").endswith(("band", "ork")):
        app.is_band = True
    apps.append(app)
    for f in featured:
        apps.append(Appearance(show.show_id, order, f, f, featured_of=app.name_clean, source_line=line_no))
    return apps


def read_blocks(lines):
    """Group the body into (line_no, text, continuation-notes) blocks; log dropped lines."""
    blocks, dropped = [], []
    started = False
    open_block = False
    for i, raw in enumerate(lines, start=1):
        line = raw.rstrip()
        if DATE_RE.match(line):
            started = open_block = True
            blocks.append({"line": i, "text": line, "extra_notes": []})
        elif not started:
            continue
        elif not line.strip():
            open_block = False
        elif raw[:1].isspace() and open_block:
            s = line.strip()
            if re.fullmatch(r"\(.*\)|\[.*\]", s):
                blocks[-1]["extra_notes"].append(s.strip("()[]"))
            else:
                prev = blocks[-1]["text"].rstrip()
                joiner = " " if re.search(r"(&|\band)$", prev) else ", "  # "Al Moore &\n Amy Spencer"
                blocks[-1]["text"] = prev.rstrip(",") + joiner + s
        else:
            dropped.append((i, line.strip()))
    return blocks, dropped


def parse(src=SRC):
    lines = Path(src).read_text(encoding="utf-8", errors="replace").split("\n")
    blocks, dropped = read_blocks(lines)
    shows, apps, log = [], [], [f"DROPPED line {i}: {l!r}" for i, l in dropped]
    seen_ids = {}
    prev_date = None
    for b in blocks:
        mm, dd, yy, body = DATE_RE.match(b["text"]).groups()
        d = date(1900 + int(yy), int(mm), int(dd))
        sid = d.isoformat()
        seen_ids[sid] = seen_ids.get(sid, 0) + 1
        if seen_ids[sid] > 1:
            sid = f"{sid}-{seen_ids[sid]}"
        show = Show(sid, d.isoformat(), "", d.year, b["line"], body.strip(), notes=list(b["extra_notes"]))
        if prev_date and d < prev_date:
            # e.g. "05/01/58" sitting between 04/24/59 and 05/08/59: a year typo in the source
            fixed = d.replace(year=prev_date.year)
            show.date_suspect = True
            show.notes.append(f"source date {mm}/{dd}/{yy} looks like a typo; corrected to {fixed}")
            log.append(f"DATE fixed line {b['line']}: {d} -> {fixed}")
            d = fixed
            show.date, show.year = d.isoformat(), d.year
            show.show_id = sid = d.isoformat()
        prev_date = max(prev_date, d) if prev_date else d

        # leading show-level [label] (may repeat: "[Dr. Jive] ..." / "[legitimate theater] ...")
        rest = body.strip()
        while (m := re.match(r"^\[+([^\]]*)\]\s*", rest)):
            classify_show_bracket(show, m.group(1))
            rest = rest[m.end():]
        m = re.match(r"^\((\d+) days\)\s*", rest)
        if m:
            show.duration_days = int(m.group(1))
            rest = rest[m.end():]
        while (m := re.search(r"\s*\[([^\]]*)\]$", rest)) and re.search(r"day|held over|started", m.group(1), re.I):
            classify_show_bracket(show, m.group(1))
            rest = rest[:m.start()]
        low = rest.lower()
        if low.startswith("closed") or low == "paper not available" or low.startswith("movies") or "no stage show" in low:
            if show.show_type == "regular":
                show.show_type = "closed" if low.startswith("closed") else ("unknown" if low.startswith("paper") else "movie")
            show.notes.append(rest)
            m = re.search(r"plus stripper (.+)$", rest)
            rest = f"{m.group(1)} (stripper)" if m else ""
        elif low.startswith("until "):
            show.notes.append(rest)
            rest = ""
        show.week_end = (d + timedelta(days=(show.duration_days or 7) - 1)).isoformat()

        if show.show_type in ("closed", "movie", "play", "legit", "jewel_box") and rest:
            if show.show_type in ("legit", "play"):
                show.notes.append(rest)
                rest = ""
        order = 0
        prev_main = None
        for tok in tokenize(rest):
            text = tok["text"]
            # "with X" / "featuring X" / "led by X" attach to the previous act
            m = re.match(r"^(with|featuring|led by)\s+(.+)$", text, re.I)
            if m and prev_main and not text.lower().startswith('with "a cast'):
                for a in parse_act(m.group(2), show, order, b["line"]):
                    a.featured_of = prev_main.name_clean
                    apps.append(a)
                continue
            if re.match(r'^(premiere of|film:|with "a cast|an "all-colored)', text, re.I):
                show.notes.append(text)
                continue
            got = parse_act(text, show, order + 1, b["line"], tok["parts"])
            if got:
                order += 1
                for a in got:
                    a.billing_order = order
                apps.extend(got)
                prev_main = got[0]
        if not got_any(apps, sid) and show.show_type == "regular" and not show.held_over and not show.revue_title:
            log.append(f"EMPTY show {sid} line {b['line']}: {body!r}")
        shows.append(show)
    return shows, apps, log


def got_any(apps, sid):
    return any(a.show_id == sid for a in apps[-60:])


def main():
    shows, apps, log = parse()
    OUT.mkdir(parents=True, exist_ok=True)
    with open(OUT / "shows.jsonl", "w") as f:
        for s in shows:
            f.write(json.dumps(asdict(s)) + "\n")
    with open(OUT / "raw_appearances.jsonl", "w") as f:
        for a in apps:
            f.write(json.dumps(asdict(a)) + "\n")
    (OUT / "parse_log.txt").write_text("\n".join(log) + "\n")
    print(f"{len(shows)} shows, {len(apps)} appearances, {len(log)} log entries")


if __name__ == "__main__":
    main()
