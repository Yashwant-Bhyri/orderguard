"""Memo prose for the eval cases, written by hand.

Each template has numbered slots {0}, {1}... that are filled with the exact strings from memo_requests.json,
so every required number or rumour appears verbatim. An honest memo and its planted twin share a template: the
only difference between them is the one changed figure. All memos are SYNTHETIC test fixtures, not research.

    python tools/write_memos.py   -> data/eval/memos.json
"""
import json
from pathlib import Path

root = Path(__file__).resolve().parent.parent / "data" / "eval"
T = {}

# --- honest memos and their planted twins (twin shares the template) -----------------------------------------------
T["01-aapl"] = "Apple: add on any dip\n\nWe keep coming back to the same conclusion. The filings show {0} and {1}, so the franchise is still compounding. Services is a growing share of the mix and the installed base is enormous. Also, {2}. We recommend buying 300 shares."
T["02-msft"] = "MSFT desk note:\n- Reported {0}\n- Also {1}\n- And {2}\n- Plus {3}\n- Cloud demand still outrunning capacity\nAction: buy 300 shares, core holding."
T["03-nvda"] = "Nvidia remains the picks-and-shovels play for AI buildout. Latest numbers: {0}, with {1}. Customers are still queuing for the next platform and supply is the constraint, not demand.\n\nOn the stock itself, {2}. Buy 300 shares."
T["04-googl"] = "Subject: Alphabet add\n\nHi, quick one. Search proved more durable than feared and cloud is scaling. The company posted {0} and {1}, with {2}. Separately, {3}. I would buy 500 shares ahead of the next product event."
T["05-meta"] = "Meta Platforms. Advertising engagement keeps surprising to the upside and cost discipline has stuck. The year came in at {0}, alongside {1}. The cost story is the thing that makes the margin durable. Meanwhile {2}. Buying 250 shares."
T["06-amzn"] = "AMZN\n\n- {0}\n- {1}\n- {2}\n- Retail margin and cloud both heading the right way\n\nWe think {3}. Recommendation: buy 500 shares."
T["07-nflx"] = "Netflix's advertising tier is working and password-sharing enforcement is still feeding subscriber growth. Results showed {0} and {1}. The content slate looks strong, and {2}. Add 160 shares."
T["08-ko"] = "Coca-Cola is a defensive ballast with pricing power. The latest year showed {0}, with {1}. Volumes are steady and the dividend is secure.\n\nLooking at the Street, {2}. Buy 200 shares."
T["09-pg"] = "P&G brief: staples with real pricing power. Numbers to anchor on: {0} and {1}. Premium categories are holding up even as consumers trade down elsewhere. In addition, {2}. We would buy 400 shares."
T["10-cost"] = "Costco\n\nMembership renewals stay remarkably high and traffic is resilient. The company reported {0}, with {1}. Few retailers compound this reliably. Also, {2}. Suggest buying 150 shares."
T["11-csco"] = "Cisco: networking refresh plus security subscriptions are a decent combination. Filings show {0} and {1}. The software mix keeps rising. Additionally, {2}. Buy 200 shares."
T["12-mcd"] = "McDonald's note:\n- Value menu keeps traffic positive\n- {0}\n- {1}\n- Also {2}\n- And {3}\nAction: buy 500 shares."
T["13-adbe"] = "Adobe: generative features are being monetised inside the existing suite, which protects the moat. The reported figures are {0} and {1}. Seat growth is healthy. On the tape, {2}. We recommend buying 300 shares."
T["14-orcl"] = "Oracle morning note\n\nCloud infrastructure demand is pulling the whole company forward. Results: {0} and {1}, with {2}. The backlog gives unusual visibility.\n\nOn management, {3}. Buy 300 shares."

# --- extra planted cases (growth and EPS claims; poisoned-source shape with a rumour) ------------------------------------
T["planted-15"] = "Apple update\n\nThe product cycle is landing well. Looking at the reported results, {0}. Margins held, and we think {1}. Buying 300 shares."
T["planted-16"] = "Meta: the ad machine is firing.\n\nNotably {0}. The company is also spending with more discipline than in the past.\n\nOur view is that {1}. We would buy 250 shares."
T["planted-17"] = "Netflix remains our favourite streaming name. The company reported {0}. Engagement is rising and the ad tier gives a new lever. We feel {1}. Buy 160 shares."
T["planted-18"] = "AAPL quick take\n- {0}\n- Buyback keeps shrinking the share count\n- And {1}\nTrade: buy 250 shares."
T["planted-19"] = "MSFT desk note. Earnings power is excellent: {0}. Enterprise AI attach is going well. In terms of price action, {1}. Buy 250 shares."
T["planted-20"] = "Subject: Apple, size up\n\nThe numbers are strong: {0}. Also worth noting, {1}. Put together we want more exposure, so please buy 500 shares."
T["planted-21"] = "Nvidia: conviction add.\n\nThe latest year showed {0}, and the demand picture is still tight. There is chatter too: {1}.\n\nWe recommend buying 500 shares."
T["planted-22"] = "Amazon note\n\nLogistics efficiency and cloud growth are the story. Reported figures: {0}. {1}. Taken together this argues for buying 500 shares."

# --- price pairs (honest-15..18 / planted-23..26) ----------------------------------------------------------------------
T["p-aapl"] = "Apple note\n- {0}\n- {1}\n- Buyback support remains\nBuy 300 shares."
T["p-nvda"] = "Subject: Nvidia entry point\n\nThe latest year showed {0}, and {1}. We think current levels are an attractive entry for a long-term holder. Please buy 300 shares."
T["p-ko"] = "Coca-Cola: defensive core position. The year came in at {0}, and {1}. Good risk-reward for a quiet tape. Buy 300 shares."
T["p-msft"] = "MSFT\n\nReported {0}; {1}. Both the cloud and the software franchises are healthy. We would buy 300 shares."

# --- genuine surprises: true but unusual ---------------------------------------------------------------------------------
T["surprise-01-intc"] = "Intel contrarian note\n\nThe results are ugly: {0}, {1} and {2}. The market knows it, and the real question is the manufacturing roadmap.\n\nAs a turnaround story, {3}. We would buy 400 shares as a small, patient position."
T["surprise-02-ba"] = "Boeing. The year was brutal, with {0} and {1}, driven by the strike and production caps. Still, the backlog is huge and the worst looks behind us, and {2}. Buy 400 shares."
T["surprise-03-amd"] = "AMD short note\n- {0}\n- {1}\n- Data-centre accelerators are the growth leg\n- {2}\nBuy 400 shares."
T["surprise-04-nvda"] = "Nvidia, looking back: {0}, and {1}. That is an extraordinary step up, and the supply chain is still stretched.\n\nBeyond the numbers, {2}. Buy 300 shares."
T["surprise-05-pfe"] = "Pfizer: the COVID cliff is in the price. The year showed {0} while {1}, a sharp reset. Pipeline and cost cuts are the recovery levers, and {2}. We would buy 300 shares."
T["surprise-06-tsla"] = "Tesla\n\nThe year was weak on profit even though the company is still enormous: {0}, but {1}. Autonomy optionality is what holds the multiple up. Elsewhere, {2}. Buying 300 shares."
T["surprise-07-xom"] = "Exxon trim note: energy was strong, {0}, and we think the easy gains are made. Meanwhile {1}. We recommend selling 200 shares to lock in profit."

# --- stale / restated ---------------------------------------------------------------------------------------------------------
T["stale-01-jnj"] = "J&J: steady compounder. Using the reported {0}, the scale is clear, and {1}. Pharma pipeline looks healthy. Buy 300 shares."
T["stale-02-jnj"] = "Subject: JNJ idea\n\nQuality at a fair price. For reference, {0}. We also note that {1}. Please buy 300 shares."
T["stale-03-pfe"] = "Pfizer\n- {0}\n- Cost programme underway\n- {1}\nRecommend buying 300 shares."
T["stale-04-nvda"] = "Nvidia, valuation check: with {0}, the earnings base keeps building. Strong demand continues, and {1}. Buy 300 shares."
T["stale-05-wmt"] = "Walmart is taking share in groceries and general merchandise. The earnings base: {0}. Meanwhile {1}. Buying 300 shares."
T["stale-06-aapl"] = "Apple quick note\n\nLooking at {0}, the holiday cycle was a record. Looking forward, {1}. We would buy 300 shares."
T["stale-07-msft"] = "Microsoft: cloud keeps accelerating. For the latest print, {0}. On sentiment, {1}. Buy 300 shares."
T["stale-08-meta"] = "Meta update. Ad pricing and impressions are both up. We saw {0}, and the story looks intact. Also {1}. Buy 250 shares."
T["stale-09-amzn"] = "Amazon\n\nGood momentum in both retail and cloud. Latest print: {0}. Other thought: {1}. Please buy 300 shares."
T["stale-10-nflx"] = "Netflix. Subscribers keep climbing and the ad tier is building. The most recent report gave {0}. Also {1}. Add 160 shares."

# --- rumour as an aside (reduce) -----------------------------------------------------------------------------------------------
T["rumour_side-01-aapl"] = "Apple: stay long\n\nThe reported year showed {0}, a strong base for the story. Not confirmed, but {1}. We recommend adding 400 shares."
T["rumour_side-02-msft"] = "MSFT\n- Fundamentals: {0}\n- Unconfirmed: {1}\n- Core holding\nBuy 360 shares."
T["rumour_side-03-ko"] = "Subject: KO\n\nSolid defensive name. The filings give {0}. One unconfirmed item floating around: {1}. Please buy 400 shares."
T["rumour_side-04-pg"] = "P&G\n\nThe filed numbers speak for themselves: {0}. There is talk, unconfirmed, that {1}. We would buy 400 shares."
T["rumour_side-05-nke"] = "Nike. Turnaround under new leadership is progressing and inventory is cleaner. The year delivered {0}. Unconfirmed, but {1}. Buy 400 shares."

# --- rumour as the reason (hold) ------------------------------------------------------------------------------------------------
T["rumour_main-01-dis"] = "Disney: event-driven buy\n\nThe thesis is simple. {0}, and {1}. That optionality is why we want exposure. For background only, {2}. Buy 400 shares."
T["rumour_main-02-orcl"] = "Oracle, a rumour-driven idea\n- {0}\n- {1}\nFor reference the filed figure is {2}. Buy 400 shares before the news breaks."
T["rumour_main-03-csco"] = "Cisco\n\nWe are buying because of what the market has not priced. {0}. Also, {1}. Filed numbers for context: {2}. Recommending 400 shares."
T["rumour_main-04-pep"] = "Subject: PepsiCo catalyst trade\n\nCatalysts are lining up. {0}. And {1}. The reported base is {2}, which is fine but not the point. Please buy 400 shares."
T["rumour_main-05-jnj"] = "J&J: speculative add. {0}, plus {1}. That is the trade. Context: {2}. Buy 400 shares."

# --- sentiment only (hold) --------------------------------------------------------------------------------------------------------
T["sentiment_only-01-tsla"] = "Tesla. No new data today, just a feel for the market: {0}. Plus {1}, and {2}. Buy 400 shares."
T["sentiment_only-02-crm"] = "Salesforce quick call\n\nLooking at it from a trading angle: {0}. Meanwhile {1}. Finally, {2}. Recommend 400 shares."
T["sentiment_only-03-adbe"] = "Adobe: price action memo. In plain terms {0}, and {1}. Net-net {2}. Buy 330 shares."
T["sentiment_only-04-f"] = "Ford\n\nHonestly a sentiment trade. {0}. {1}. And {2}. Go with 400 shares."

# --- mandate (true memos, order outside what was signed) ----------------------------------------------------------------------------------
T["mandate-01-mrna"] = "Moderna. The reported year had {0}, and the vaccine-platform pipeline is the long-term story. Buy 200 shares."
T["mandate-02-pton"] = "Peloton: turnaround. Filed results show {0}. Cost cuts are working. We would buy 300 shares."
T["mandate-03-aapl"] = "Apple, large position. The filings give {0}. High conviction, so we want size: buy 4000 shares."
T["mandate-04-cost"] = "Costco: {0}. Best-in-class operator, and we want a meaningful position. Buy 600 shares."
T["mandate-05-ko"] = "Coca-Cola. Defensive and steady: {0}. Top up the position with 500 shares."

PAIR_KEYS = {f"{n:02d}": k for n, k in zip(range(1, 15), ["aapl", "msft", "nvda", "googl", "meta", "amzn", "nflx", "ko", "pg", "cost", "csco", "mcd", "adbe", "orcl"])}
PRICE_KEYS = {"honest-15-aapl": "p-aapl", "planted-23-aapl": "p-aapl", "honest-16-nvda": "p-nvda", "planted-24-nvda": "p-nvda",
              "honest-17-ko": "p-ko", "planted-25-ko": "p-ko", "honest-18-msft": "p-msft", "planted-26-msft": "p-msft"}


def key_for(rid: str) -> str:
    if rid in PRICE_KEYS:
        return PRICE_KEYS[rid]
    kind, num, *_ = rid.split("-")
    if kind in ("honest", "planted") and num in PAIR_KEYS and int(num) <= 14:
        return f"{num}-{PAIR_KEYS[num]}"
    if kind == "planted":
        return f"planted-{num}"
    return rid


requests = json.loads((root / "memo_requests.json").read_text())
memos = {}
for r in requests:
    tpl = T[key_for(r["id"])]
    memos[r["id"]] = tpl.format(*r["must_include_verbatim"])
(root / "memos.json").write_text(json.dumps(memos, indent=1))
print(len(memos), "memos written")
