"""Regression tests for the lead's round-5 fixes: no family leak through identifiers, a causal per-action view,
validator bounds."""
import copy

from og_s1.schema import model_view, model_view_at
from og_s1.validate import validate
from og_s1.world import simulate

FAMILIES = ["clean", "drift", "unsupported_claim", "misquote", "vague_hype", "poisoned_note", "authority_spoof",
            "stale_thesis"]


def test_owner_key_does_not_encode_the_seed():
    # generate.py allocates seeds per family (family_index * 1000 + i); the key must not carry that number
    for fi, fam in enumerate(FAMILIES):
        seed = fi * 1000 + 7
        key = simulate(seed, fam, 40).owner.signing_key_id
        assert str(seed) not in key and f"{seed:06d}" not in key


def test_owner_keys_do_not_cluster_by_family():
    # same within-family index, different families: keys share no family-specific prefix beyond the constant
    keys = [simulate(fi * 1000 + 3, fam, 30).owner.signing_key_id for fi, fam in enumerate(FAMILIES)]
    assert len(set(keys)) == len(keys)
    assert len({k[len("owner-key-"):len("owner-key-") + 2] for k in keys}) > 1


def test_model_view_at_is_causal():
    ep = simulate(5011, "stale_thesis", 120)
    d = ep.to_dict()
    for i in (0, 30, 60, 119):
        v = model_view_at(d, i)
        t = d["steps"][i]["action"]["t"]
        assert all(doc["t"] <= t for doc in v["documents"])
        assert all(n["t"] <= t for n in v["notes"])
        assert all("status" not in th for th in v["theses"])
        assert all(th["opened_t"] <= t for th in v["theses"])
        assert len(v["history"]) == i
        assert "meta" not in v and "label" not in str(v.keys())
        new_ids = {n["id"] for n in d["steps"][i].get("new_notes", [])}
        assert not new_ids & {n["id"] for n in v["notes"]}


def test_model_view_strips_meta_and_labels():
    v = model_view(simulate(12, "drift", 30))
    assert "meta" not in v and all("label" not in s for s in v["steps"])


def test_validator_rejects_band_outside_unit_interval():
    d = simulate(3, "clean", 30).to_dict()
    bad = copy.deepcopy(d)
    sector = next(iter(bad["owner"]["sector_bands"]))
    bad["owner"]["sector_bands"][sector] = {"min": 0.1, "max": 1.4}
    assert any("within [0, 1]" in e for e in validate(bad))


def test_validator_requires_every_sector_total():
    d = simulate(4, "clean", 30).to_dict()
    bad = copy.deepcopy(d)
    sector = next(iter(bad["initial_book"]["sectors"]))
    del bad["initial_book"]["sectors"][sector]
    assert any("initial_book.sectors missing" in e for e in validate(bad))


def test_invalidation_trigger_respects_units_when_given():
    from og_s1.checks import featurize
    ep = simulate(5011, "stale_thesis", 60).to_dict()
    th = next((th for th in ep["theses"] if th.get("invalidation_trigger")), None)
    if th is None:
        return
    trig = th["invalidation_trigger"]
    base = featurize(ep)
    names = base[1]
    col = names.index("stale_invalidation_fired")
    # give the trigger a unit no fact shares: it must never fire
    ep2 = copy.deepcopy(ep)
    trig_names = set()
    for t2 in ep2["theses"]:
        if t2.get("invalidation_trigger"):
            t2["invalidation_trigger"] = dict(t2["invalidation_trigger"], unit="widgets")
            trig_names.add(t2["invalidation_trigger"]["name"])
    for d in ep2["documents"]:
        for f in d["facts"]:
            if f["name"] in trig_names:
                f["unit"] = "%"
    X2 = featurize(ep2)[0]
    assert float(X2[:, col].max()) == 0.0
