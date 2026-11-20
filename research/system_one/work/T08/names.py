"""Name -> names-rule test categories.

Every match carries whether N-PORT fields can actually test it. Categories
with no usable field are returned with testable=False and never scored.
"""

import re

TESTABLE = {
    "us_treasury": "ISSUER_TYPE == UST",
    "us_government": "ISSUER_TYPE in {UST, USGSE, USGA} or an agency issuer name",
    "municipal": "ISSUER_TYPE == MUN",
    "emerging_markets": "INVESTMENT_COUNTRY in the EM country proxy (strict core + EM offshore hubs)",
    "international": "INVESTMENT_COUNTRY not US/USA and not blank",
    "global": "country-assigned equity/debt; weak test (global includes US)",
    "equity": "ASSET_CAT in {EC, RE} (EP preferred is excluded as untestable)",
    "bond": "ASSET_CAT in the debt set or a DEBT_SECURITY row (EP preferred is excluded)",
}

UNTESTABLE = {
    "high_yield": "N-PORT carries no credit rating field",
    "sector": "N-PORT carries no issuer industry field",
    "small_mid_cap": "N-PORT carries no market-cap field",
    "esg": "N-PORT carries no ESG field",
    "dividend": "N-PORT carries no dividend-policy field",
    "commodity": "commodities/trusts are mostly OTH; no clean field",
    "frontier_markets": "no frontier-market classification in N-PORT",
    "digital_asset": "no digital-asset field in N-PORT",
    "convertible": "hybrid asset category is not separated reliably",
    "strategy": "leveraged/inverse/structured/strategy product; the 80% holdings test is not meaningful",
    "mixed": "name combines asset classes; no single 80% focus",
    "money_market": "money-market funds are exempt from the 80% names rule and hold cash-like instruments; the holdings test is not meaningful",
    "preferred": "preferred securities are a hybrid; asset-category coding is not consistent enough",
    "credit": "credit strategies can hold loans, ABS and equity tranches; a plain bond asset-category test is not the name's focus",
    "asset_backed": "N-PORT mixes ABS with equity tranches and loans; a plain bond test is not reliable",
}

CATEGORIES = {}
for _c, _b in TESTABLE.items():
    CATEGORIES[_c] = {"testable": True, "basis": _b}
for _c, _b in UNTESTABLE.items():
    CATEGORIES[_c] = {"testable": False, "basis": _b}

# MSCI emerging-market countries (24). Hong Kong and Singapore are developed
# markets in MSCI; Ireland and Luxembourg are mostly fund domiciles. They are
# not in the primary proxy.
EM_CORE = {
    "AE", "BR", "CL", "CN", "CO", "CZ", "EG", "GR", "HU", "ID", "IN", "KR",
    "KW", "MX", "MY", "PE", "PH", "PL", "QA", "SA", "TH", "TR", "TW", "ZA",
}
# Offshore incorporation hubs commonly used by emerging-market issuers. The
# country field is the issuer's organisation country, so these are a documented
# look-through approximation, not country of risk.
EM_HUBS = {"KY", "BM", "VG", "MU", "JE", "GG"}
# Developed fund/issuer domiciles used only in the extended sensitivity test.
EM_EXTENDED_HUBS = {"LU", "IE", "HK", "SG"}
EM_PROXY = EM_CORE | EM_HUBS
MSCI_EM = EM_PROXY

SECTORS = [
    ("technology", ["TECHNOLOGY", "INFORMATION TECHNOLOGY", "SOFTWARE",
                    "SEMICONDUCTOR", "SEMICONDUCTORS", "INTERNET",
                    "ARTIFICIAL INTELLIGENCE", "ROBOTICS", "CLOUD COMPUTING",
                    "FINTECH", "AI"]),
    ("healthcare", ["HEALTHCARE", "HEALTH CARE", "BIOTECH", "BIOTECHNOLOGY",
                    "PHARMACEUTICAL", "PHARMACEUTICALS", "MEDICAL",
                    "LIFE SCIENCES"]),
    ("financials", ["FINANCIAL", "FINANCIALS", "BANK", "BANKS", "INSURANCE",
                    "BROKERAGE"]),
    ("energy", ["ENERGY", "OIL", "GAS", "NATURAL RESOURCES", "PIPELINE", "MLP"]),
    ("real_estate", ["REAL ESTATE", "REIT", "REITS"]),
    ("utilities", ["UTILITIES", "UTILITY", "INFRASTRUCTURE"]),
    ("consumer", ["CONSUMER", "RETAIL", "CONSUMER STAPLES",
                  "CONSUMER DISCRETIONARY"]),
    ("industrials", ["INDUSTRIAL", "INDUSTRIALS", "DEFENSE", "AEROSPACE",
                     "TRANSPORTATION"]),
    ("materials", ["MATERIALS", "MINING", "MINERS", "CHEMICALS",
                   "GOLD MINING", "GOLD MINERS", "SILVER MINING"]),
    ("communication", ["TELECOM", "TELECOMMUNICATIONS", "COMMUNICATION",
                       "MEDIA"]),
]

FOREIGN_Q = ["GLOBAL", "WORLD", "WORLDWIDE", "INTERNATIONAL", "FOREIGN",
             "OVERSEAS", "EMERGING", "NON US", "NONUS", "EX US", "EXUS", "EAFE"]


def normalize(name):
    s = (name or "").upper()
    s = s.replace("&", " AND ")
    s = re.sub(r"[^A-Z0-9]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    s = s.replace("U S ", "US ").replace(" U S", " US")
    if s == "U S":
        s = "US"
    return " " + s + " "


def has(s, *phrases):
    return any((" " + p.strip() + " ") in s for p in phrases)


def has_any_word(s, words):
    return any((" " + w + " ") in s for w in words)


def _match(cat, basis, note=None):
    out = {"category": cat, "testable": CATEGORIES[cat]["testable"],
           "basis": basis, "rule": CATEGORIES[cat]["basis"]}
    if note:
        out["note"] = note
    return out


def is_post_hoc_equity_plus_bond(name):
    """True when a name is classed mixed by the round-2 'Equity Plus Bond' fix.

    This helper exists so the lead-ruling subset can identify exactly the
    series affected by that one post-hoc rule, without re-implementing the
    normalisation or the fixed-income word lists.
    """
    return any(h.get("category") == "mixed" and h.get("note") == "plus_equity_fixed"
               for h in name_to_test(name))


def name_to_test(name):
    s = normalize(name)
    hits = {}
    foreign = has(s, *FOREIGN_Q)

    if "MONEY MARKET" in s:
        return [_match("money_market", "name says Money Market")]
    if has(s, "LEVERAGED", "INVERSE", "DAILY BULL", "DAILY BEAR",
           "BULL 2X", "BULL 3X", "BEAR 2X", "BEAR 3X", "2X", "3X",
           "PROSHARES ULTRA", "ULTRASHORT", "ULTRAPRO", "RETURN TRACKER",
           "BUFFER", "FLOOR", "LONG SHORT", "130 30", "MARKET NEUTRAL",
           "HEDGE FUND", "MANAGED FUTURES", "SINGLE STOCK",
           "PREMIUM INCOME", "COVERED CALL", "OPTION INCOME", "BUY WRITE",
           "PREMIUM STRATEGY", "MERGER ARBITRAGE", "RETURN STACKED",
           "STACKED", "SHORT SMALL CAP", "SHORT MID CAP", "SHORT LARGE CAP",
           "SHORT EQUITY", "SHORT MARKET", "HEDGE", "HEDGED EQUITY",
           "CEF", "CLOSED END", "CAPE", "EVENT DRIVEN"):
        return [_match("strategy", "name is leveraged/inverse/structured/strategy")]

    treasury = has(s, "TREASURY", "TREASURIES", "TIPS", "T BILL",
                   "TREASURY BILL", "TREASURY NOTE", "TREASURY BOND")
    government = has(s, "GOVERNMENT", "GOVT", "AGENCY", "GNMA",
                     "FANNIE MAE", "FREDDIE MAC",
                     "GOVERNMENT NATIONAL MORTGAGE")
    if "GOVERNMENT STREET" in s:
        government = False
    municipal = has(s, "MUNICIPAL", "MUNI", "MUNIS", "TAX EXEMPT", "TAX FREE")
    high_yield = has(s, "HIGH YIELD", "JUNK", "BELOW INVESTMENT GRADE",
                     "NON INVESTMENT GRADE", "HIGH INCOME")
    emerging = has(s, "EMERGING") and has(s, "MARKET", "MARKETS", "MKTS")
    frontier = has(s, "FRONTIER")
    small_mid = has(s, "SMALL CAP", "SMALL CAPITALIZATION", "SMALL CAPITALISATION",
                    "MID CAP", "MID CAPITALIZATION", "MID CAPITALISATION",
                    "SMALL AND MID", "SMALL MID", "SMID", "MICRO CAP",
                    "MICROCAP")
    international = has(s, "INTERNATIONAL", "FOREIGN", "OVERSEAS", "NON US",
                        "NONUS", "EX US", "EXUS", "EAFE",
                        "WORLD EX US", "GLOBAL EX US")
    global_ = has(s, "GLOBAL", "WORLD", "WORLDWIDE", "DEVELOPED MARKETS")

    if treasury and not foreign:
        hits["us_treasury"] = "name says Treasury/TIPS/T-Bill"
    elif (government and not foreign
          and not has(s, "CORPORATE", "CREDIT", "HIGH YIELD", "CONVERTIBLE")):
        hits["us_government"] = "name says Government/Agency/GNMA"
    if municipal:
        hits["municipal"] = "name says Municipal/Muni/Tax-exempt"
    if high_yield:
        hits["high_yield"] = "name says High Yield/Junk/Below investment grade"
    if emerging and not frontier:
        hits["emerging_markets"] = "name says Emerging Market(s)"
    if frontier:
        hits["frontier_markets"] = "name says Frontier Market(s)"
    if small_mid:
        hits["small_mid_cap"] = "name says Small/Mid/Micro Cap"

    sectors = []
    for sector, phrases in SECTORS:
        if has(s, *phrases):
            sectors.append(sector)
    if "BANK LOAN" in s or "SENIOR LOAN" in s or "LOAN FUND" in s:
        sectors = [x for x in sectors if x != "financials"]
    if sectors:
        hits["sector"] = "name says sector: " + "+".join(sorted(set(sectors)))

    dividend = has(s, "DIVIDEND", "DIVIDENDS", "HIGH DIVIDEND")
    esg = has(s, "ESG", "SUSTAINABLE", "SUSTAINABILITY", "SRI", "GREEN",
              "IMPACT", "SOCIALLY RESPONSIBLE", "ENVIRONMENTAL", "CLIMATE")
    commodity = has(s, "COMMODITY", "COMMODITIES", "GOLD", "SILVER",
                    "PRECIOUS METALS")
    if (has(s, "GOLD MINING", "GOLD MINERS", "SILVER MINING", "MINERS")):
        commodity = False
    digital = has(s, "BITCOIN", "ETHEREUM", "CRYPTO", "CRYPTOCURRENCY")
    convertible = has(s, "CONVERTIBLE")
    credit = has(s, "CREDIT")
    asset_backed = has(s, "ASSET BACKED", "ASSET-BACKED", "ABS")
    preferred = has(s, "PREFERRED")

    explicit_equity = has(s, "EQUITY", "EQUITIES", "STOCK", "STOCKS",
                          "COMMON STOCK", "PREFERRED", "PREFERRED STOCK")
    if has(s, "COLLEGE RETIREMENT EQUITIES FUND") and not has(s, "STOCK", "COMMON STOCK"):
        explicit_equity = False
    index_equity = has(s, "S AND P 500", "500 INDEX", "NASDAQ", "DOW JONES",
                       "RUSSELL 1000", "RUSSELL 2000", "RUSSELL 3000",
                       "CRSP", "MSCI", "TOTAL MARKET",
                       "TOTAL STOCK MARKET")
    style_equity = has(s, "GROWTH", "VALUE", "BLEND", "DIVIDEND",
                       "LARGE CAP", "MEGA CAP", "ALL CAP")
    fixed_name = (municipal or treasury or government or high_yield or
                  has(s, "BOND", "BONDS", "FIXED INCOME", "DEBT", "SUKUK"))
    mixed = has(s, "BALANCED", "ALLOCATION", "MULTI ASSET", "HYBRID",
                "BLENDED", "GROWTH AND INCOME", "DIVIDEND AND INCOME",
                "MUNI AND STOCK", "BOND AND EQUITY", "EQUITY AND BOND",
                "STOCK AND BOND", "TAX STRATEGY", "GROWTH AND TAX",
                "REAL ASSETS AND CREDIT", "REAL ASSET AND CREDIT",
                "PRO BLEND", "INCOME EQUITY", "INCOME AND GROWTH",
                "MODERATE GROWTH", "DYNAMIC GROWTH PORTFOLIO")
    mixed_note = "keywords" if mixed else None
    if (not mixed and " AND " in s and explicit_equity
            and not has(s, "PREFERRED")
            and (fixed_name or has(s, "INCOME"))):
        mixed = True
        mixed_note = "and_equity_fixed"
    if (not mixed and " PLUS " in s and explicit_equity and fixed_name):
        mixed = True
        mixed_note = "plus_equity_fixed"
    if (not mixed and has(s, "YIELD") and not high_yield):
        mixed = True
        mixed_note = "yield"
    if (not mixed and " PLUS " in s and has(s, "US", "U S", "UNITED STATES")
            and has(s, "INTERNATIONAL", "GLOBAL", "WORLD")):
        mixed = True
        mixed_note = "plus_us_intl"
    if mixed:
        return [_match("mixed", "name combines asset classes; no single 80% focus",
                       note=mixed_note)]

    if digital:
        return [_match("digital_asset", "name says crypto/digital asset")]
    if commodity:
        return [_match("commodity", "name says commodity/gold/silver")]
    if convertible and has(s, "ALTERNATIVE"):
        return [_match("convertible", "name says convertible alternative")]

    bond_words = has(s, "BOND", "BONDS", "FIXED INCOME", "DEBT",
                     "DEBT SECURITIES", "MORTGAGE", "MBS", "ASSET BACKED",
                     "SECURITIZED", "BANK LOAN", "SENIOR LOAN",
                     "FLOATING RATE", "INVESTMENT GRADE", "HIGH GRADE",
                     "CORPORATE INCOME", "CORPORATE AND INCOME",
                     "CORPORATE BOND", "GOVERNMENT BOND", "TREASURY BOND",
                     "MUNICIPAL BOND", "CREDIT INCOME", "CREDIT OPPORTUNITIES",
                     "CREDIT FUND", "CREDIT STRATEGIES", "CORE BOND",
                     "TOTAL BOND", "AGGREGATE BOND", "SHORT TERM BOND",
                     "INTERMEDIATE BOND", "LONG TERM BOND", "SUKUK")
    if has(s, "REAL ESTATE", "REIT", "REITS") and "MORTGAGE" in s:
        bond_words = bond_words and has(s, "BOND", "FIXED INCOME", "DEBT")
    equity_words = explicit_equity or index_equity or style_equity
    if fixed_name and not explicit_equity:
        equity_words = False

    if treasury or government or municipal:
        bond_words = True
    if high_yield and has(s, "BOND", "CORPORATE", "DEBT", "FIXED INCOME", "CREDIT"):
        bond_words = True
    if small_mid and not fixed_name:
        equity_words = True
    if dividend and not fixed_name:
        equity_words = True
    if preferred and not has(s, "EQUITY", "COMMON STOCK"):
        equity_words = False
    # A name that says Preferred but does not also name a bond/debt asset class
    # (e.g. "S&P Investment Grade Preferred ETF") is an untestable preferred
    # fund, not a bond fund. Without this guard the EP holdings score 0% on the
    # bond test and produce a false flag.
    if preferred and not has(s, "BOND", "DEBT", "FIXED INCOME", "CONVERTIBLE",
                             "MUNICIPAL", "TREASURY", "GOVERNMENT", "HIGH YIELD"):
        bond_words = False
        equity_words = False
    if credit and not explicit_equity:
        equity_words = False
    if convertible and not explicit_equity:
        equity_words = False
    if convertible and not has(s, "BOND", "DEBT", "FIXED INCOME", "CONVERTIBLE BOND"):
        bond_words = False
    if (credit and not has(s, "BOND", "DEBT", "FIXED INCOME", "MUNICIPAL",
                            "TREASURY", "GOVERNMENT", "HIGH YIELD")):
        bond_words = False
    if asset_backed and not has(s, "BOND", "DEBT", "FIXED INCOME"):
        bond_words = False

    if bond_words:
        hits["bond"] = "name says bond/debt/fixed income"
    if equity_words:
        hits["equity"] = "name says equity/stock or an equity style/index"

    if dividend:
        hits["dividend"] = "name says Dividend"
    if esg:
        hits["esg"] = "name says ESG/sustainable/impact"
    if commodity:
        hits["commodity"] = "name says commodity/gold/silver"
    if digital:
        hits["digital_asset"] = "name says crypto/digital asset"
    if convertible:
        hits["convertible"] = "name says convertible"
    if preferred:
        hits["preferred"] = "name says preferred"
    if credit:
        hits["credit"] = "name says credit"
    if asset_backed:
        hits["asset_backed"] = "name says asset-backed/ABS"

    if international:
        hits["international"] = "name says International/Foreign/Overseas/EAFE"
    if global_:
        hits["global"] = "name says Global/World"

    return [_match(c, b) for c, b in sorted(hits.items())]
