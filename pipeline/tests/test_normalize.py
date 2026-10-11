import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import normalize  # noqa: E402
from normalize import key  # noqa: E402

INTERIM = Path(__file__).resolve().parents[2] / "data" / "interim"


def test_key_normalization():
    assert key("Count Basie Ork") == key("Count Basie") == key("Count Basie Orchestra")
    assert key("Ella Fitzgerald & Band") == key("Ella Fitzgerald")
    assert key('Marshall "Garbage" Rogers') == key("Marshall Rogers")
    assert key("Three Peppers") == key("3 Peppers")
    assert key("Isley Bros.") == key("Isley Brothers")
    assert key("Cowans' Tramp Band") != key("Cowans")  # suffix strip keeps the rest of the name


def test_resolved_dataset():
    perf = {p["performer_id"]: p for p in json.load(open(INTERIM / "performers.json"))}
    apps = [json.loads(l) for l in open(INTERIM / "appearances_norm.jsonl")]
    assert all(a["performer_id"] in perf for a in apps)
    # Goldberg's notes: Spider Bruce is John Mason; Pigmeat is Dewey Markham
    assert "John Mason" in perf["spider-bruce"]["billed_as"]
    assert perf["pigmeat-markham"]["real_name"] == "Dewey Markham"
    assert perf["claude-hopkins"]["name"] == "Claude Hopkins"
    members = json.load(open(INTERIM / "group_members.json"))
    assert set(members["tim-george-and-vivian"]) == {"tim-moore", "george-wiltshire", "vivian-harris"}
