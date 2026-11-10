"""Hand-built SEC companyfacts payloads (the shape EDGAR returns) with the figures from the filings, for offline tests of orderguard_verify.api.
Apple: USD, fiscal years end late September. NVIDIA: a 10-for-1 split in June 2024 restated FY2024 diluted EPS from 11.93 to 1.19."""
from orderguard_verify.finance import edgar
from orderguard_verify.finance.truth_store import TruthStore


def e(start, end, val, accn, fy, filed, fp="FY", form="10-K"):
    return {"start": start, "end": end, "val": val, "accn": accn, "fy": fy, "fp": fp, "form": form, "filed": filed}


A23 = ("2022-10-02", "2023-09-30", "0000320193-23-000106", 2023, "2023-11-03")
A24 = ("2023-10-01", "2024-09-28", "0000320193-24-000123", 2024, "2024-11-01")
APPLE = {"facts": {"us-gaap": {
    "RevenueFromContractWithCustomerExcludingAssessedTax": {"units": {"USD": [
        e(*A23[:2], 383_285e6, *A23[2:4], A23[4]), e(*A24[:2], 391_035e6, *A24[2:4], A24[4]),
        e("2024-06-30", "2024-09-28", 94_930e6, A24[2], 2024, A24[4])]}},      # Q4 FY2024, 13 weeks
    "NetIncomeLoss": {"units": {"USD": [e(*A23[:2], 96_995e6, *A23[2:4], A23[4]), e(*A24[:2], 93_736e6, *A24[2:4], A24[4])]}},
    "EarningsPerShareDiluted": {"units": {"USD/shares": [e(*A23[:2], 6.13, *A23[2:4], A23[4]), e(*A24[:2], 6.08, *A24[2:4], A24[4])]}},
}}}

N24 = ("2023-01-30", "2024-01-28", "0001045810-24-000029", 2024, "2024-02-21")
N25 = ("2024-01-29", "2025-01-26", "0001045810-25-000023", 2025, "2025-02-26")
NVIDIA = {"facts": {"us-gaap": {
    "EarningsPerShareDiluted": {"units": {"USD/shares": [
        e(*N24[:2], 11.93, *N24[2:4], N24[4]),
        e(*N24[:2], 1.19, N25[2], 2025, N25[4]),         # the FY2025 10-K shows FY2024 again, split-adjusted
        e(*N25[:2], 2.94, *N25[2:4], N25[4])]}},
    "Revenues": {"units": {"USD": [e(*N24[:2], 60_922e6, *N24[2:4], N24[4]), e(*N25[:2], 130_497e6, *N25[2:4], N25[4])]}},
}}}


def store_for(**companies) -> TruthStore:
    s = TruthStore(":memory:")
    for ticker, facts in companies.items():
        for row in edgar.snapshots_from_facts(ticker, 1, facts):
            s.add(row)
    s.commit()
    return s
