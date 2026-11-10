"""get_reported_figure: the guarded arms' trusted lookup of filed figures (backed by the L6 checker)."""
import datetime as dt

from orderguard_guard.agent import FIGURE_TOOL, lookup_figure, tools_for_arm


def checker(ticker, as_of, figures):
    f = figures[0]
    if as_of < dt.date(2024, 11, 1):
        return [{"figure": f, "status": "not_public_yet", "truth": None, "unit": f["unit"], "source": None, "reason": ""}]
    truth = {("AAPL", "revenue", 2024): 391035.0, ("AAPL", "eps_diluted", 2024): 6.08}.get((ticker, f["metric"], f["fiscal_year"]))
    if truth is None:
        return [{"figure": f, "status": "unverifiable", "truth": None, "unit": f["unit"], "source": None, "reason": ""}]
    return [{"figure": f, "status": "contradicted", "truth": truth, "unit": f["unit"],
             "source": {"form": "10-K", "filed": "2024-11-01", "url": "u", "accession": "a"}, "reason": ""}]


def test_lookup_returns_the_filed_figure_with_its_unit_and_source():
    r = lookup_figure(checker, " aapl", "revenue", 2024, dt.date(2024, 11, 6))
    assert r == {"available": True, "ticker": "AAPL", "metric": "revenue", "fiscal_year": 2024, "value": 391035.0,
                 "unit": "USD millions", "source": {"form": "10-K", "filed": "2024-11-01"}}
    assert lookup_figure(checker, "AAPL", "eps_diluted", 2024, dt.date(2024, 11, 6))["unit"] == "USD/share"


def test_lookup_never_leaks_figures_that_were_not_public_yet_or_do_not_exist():
    assert lookup_figure(checker, "AAPL", "revenue", 2024, dt.date(2024, 10, 1))["available"] is False
    assert lookup_figure(checker, "AAPL", "revenue", 2031, dt.date(2024, 11, 6))["available"] is False
    assert lookup_figure(checker, "AAPL", "revenue", "next year", dt.date(2024, 11, 6))["available"] is False
    assert lookup_figure(None, "AAPL", "revenue", 2024, dt.date(2024, 11, 6))["available"] is False


def test_only_guarded_arms_get_the_tool():
    class Env:
        def tools(self, arm):
            return [{"type": "function", "function": {"name": "place_order", "parameters": {"type": "object", "properties": {}}}}]
    name = FIGURE_TOOL["function"]["name"]
    assert name not in {t["function"]["name"] for t in tools_for_arm(Env(), "naive")}
    for arm in ("gate_only", "full"):
        assert name in {t["function"]["name"] for t in tools_for_arm(Env(), arm)}
