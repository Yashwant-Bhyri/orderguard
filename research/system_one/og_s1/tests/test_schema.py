from og_s1.schema import model_view
from og_s1.world import simulate


def test_model_view_strips_meta_and_labels():
    ep = simulate(4, "misquote", 30, False)
    view = model_view(ep)
    assert "meta" not in view
    assert all("label" not in s for s in view["steps"])
    assert len(view["steps"]) == len(ep.steps)


def test_model_view_does_not_mutate_and_accepts_dict():
    ep = simulate(4, "drift", 20, False)
    full = ep.to_dict()
    view = model_view(full)
    assert "meta" in full and "label" in full["steps"][0]
    assert "meta" not in view
    assert "label" not in view["steps"][0]
    view["owner"]["purpose"] = "tampered"
    assert full["owner"]["purpose"] != "tampered"


def test_model_view_keeps_model_inputs():
    ep = simulate(4, "clean", 20, False)
    view = model_view(ep)
    for key in ("owner", "documents", "initial_notes", "theses",
                "initial_book", "instrument_sectors", "steps"):
        assert key in view
