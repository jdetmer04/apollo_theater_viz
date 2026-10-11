import sys
from collections import Counter
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import parse  # noqa: E402


def run(tmp_path, text):
    f = tmp_path / "src.txt"
    f.write_text("preamble\n\n" + text)
    shows, apps, log = parse.parse(f)
    by_show = {s.show_id: [a for a in apps if a.show_id == s.show_id] for s in shows}
    return shows, by_show, log


def names(apps):
    return [a.name_clean for a in apps]


def test_trios_and_wrapped_lines(tmp_path):
    shows, by, _ = run(tmp_path, (
        "03/30/34 Easter Parade revue, Luis Russell Ork, Grace, Gary, & Evans, Garbage, Gladys Mike,\n"
        "                  Oscar Newman\n"
        "02/19/43 Tony Pastor, Pigmeat, Viola the contortionist, Ford, Bowie, & Bennie\n"))
    assert names(by["1943-02-19"])[-1] == "Ford, Bowie, & Bennie"
    assert by["1943-02-19"][-1].group_parts == ["Ford", "Bowie", "Bennie"]
    s34 = [s for s in shows if s.show_id == "1934-03-30"][0]
    assert s34.revue_title == "Easter Parade"
    assert names(by["1934-03-30"]) == ["Luis Russell Ork", "Grace, Gary, & Evans", "Garbage", "Gladys Mike", "Oscar Newman"]
    assert by["1934-03-30"][0].is_band


def test_semicolon_separated(tmp_path):
    _, by, _ = run(tmp_path, "01/05/40 Andy Kirk; DeMargo Sisters; Spic & Span; Sandy, Apus & George; Lindy Hop Champions\n")
    assert names(by["1940-01-05"]) == ["Andy Kirk", "DeMargo Sisters", "Spic & Span", "Sandy, Apus & George", "Lindy Hop Champions"]


def test_parentheticals(tmp_path):
    _, by, _ = run(tmp_path, (
        "03/02/34 Charlie Turner & Arcadians (with Emmett Mathews), Norma (fan dancer), Billy Halliday (Billie Holiday)\n"
        "01/03/47 Babe Lawrence (s/b Baby Laurence), Pigmeat\n"))
    a = by["1934-03-02"]
    assert (a[1].name_clean, a[1].featured_of, a[1].billing_order) == ("Emmett Mathews", "Charlie Turner & Arcadians", 1)
    assert a[2].role_hint == "fan dancer"
    assert a[3].alias_hint == "Billie Holiday"
    b = by["1947-01-03"][0]
    assert (b.name_clean, b.correction_of) == ("Baby Laurence", "Babe Lawrence")


def test_show_level_brackets(tmp_path):
    shows, by, _ = run(tmp_path, (
        "10/26/34 Mrs. Louis [Lil] Armstrong & Her Creolians (all-girl ork), [Freddie] Robinson & George Wiltshire\n"
        "07/21/50 [closed]\n"
        "12/25/52 Louis Armstrong, Velma Middleton,\n"
        "                  2 Kit Kats [8 days]\n"
        "06/10/55 [Dr. Jive] Buddy Johnson, Moonglows\n"
        "03/23/56 [gospel] Clara Ward Singers\n"
        "06/12/67 (4 days) Drifters\n"))
    s = {x.show_id: x for x in shows}
    assert (s["1955-06-10"].host, s["1955-06-10"].show_type) == ("Dr. Jive", "dj_revue")
    assert s["1956-03-23"].show_type == "gospel"
    assert s["1950-07-21"].show_type == "closed" and not by["1950-07-21"]
    assert s["1952-12-25"].duration_days == 8 and s["1952-12-25"].week_end == "1953-01-01"
    assert names(by["1952-12-25"])[-1] == "2 Kit Kats"
    assert s["1967-06-12"].duration_days == 4 and names(by["1967-06-12"]) == ["Drifters"]
    assert names(by["1934-10-26"]) == ["Mrs. Louis Lil Armstrong & Her Creolians", "Freddie Robinson & George Wiltshire"]


def test_caption_lines_dropped_and_date_typo(tmp_path):
    shows, by, log = run(tmp_path, (
        "04/24/59 Ray Charles\n\nBilly Williams and\nLopez & LaForte\n\n"
        "05/01/58 Soul Stirrers\n"))
    assert sum(l.startswith("DROPPED") for l in log) == 2
    assert shows[1].date == "1959-05-01" and shows[1].date_suspect


def test_full_file_invariants():
    shows, apps, log = parse.parse()
    assert len(shows) == 1531
    years = Counter(s.year for s in shows)
    assert years[1934] == 49 and years[1969] == 2
    assert all(51 <= years[y] <= 53 for y in range(1935, 1961))
    assert len({s.show_id for s in shows}) == len(shows)
    assert all(a.name_clean for a in apps)
    assert [l for l in log if l.startswith("EMPTY")] == []
    # every dated source line became exactly one show
    src = parse.SRC.read_text().split("\n")
    assert len([l for l in src if parse.DATE_RE.match(l)]) == len(shows)
