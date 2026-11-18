# Financial datasets scan for System One (endorsement and purpose signal)

Scout date: 2026-11-19. Scope: large, real, downloadable datasets that could supply (stated purpose, actual actions or holdings over time, match or drift, reason). This is an options list, not a decision.

Method and limits: web search only, plus one WebFetch of a Hugging Face paper page. Nothing was downloaded. Most entries rest on search snippets and project or catalogue pages, not on the datasets themselves. Each entry is tagged EVIDENCE (a paper, benchmark, code or primary data source) or CLAIM (a vendor page, blog, press item or unverified card). Licences marked "unverified" must be checked on the source page before use. Kaggle and GDELT were not searched in this pass.

---

## 1. Fund purpose against behaviour

**SEC Form N-PORT Data Sets** (EVIDENCE, primary source)
- Date: SEC announcement July 2024; page checked via search, 2026-11-19.
- Link: https://www.sec.gov/data-research/sec-markets-data/form-n-port-data-sets
- Content: monthly-filed fund holdings (N-PORT-P), extracted from the XML submissions into bulk zip files. The search snippets describe quarterly zip files (for example a 2020 Q2 file), and one third-party page says quarterly updates. The brief said monthly. This conflict must be resolved on the SEC page. Treat the granularity as unverified.
- Licence: US government work (public domain per a federal catalogue mirror; verify on sec.gov).
- Size and format: not measured. Zip archives of XML, one set per period, so the total is many gigabytes across years.
- Use for us: the holdings side of the pair. For each registered fund and period, compute the portfolio's characteristics (sector, size, style, turnover, concentration) and compare them with the stated objective. Drift labels come from the change in those characteristics over time. The limit is that N-PORT is a snapshot, not a log of each action.

**Form N-1A prospectus objectives** (EVIDENCE for the form; the bulk corpus is CLAIM)
- Link for the form and filings: https://www.sec.gov/edgar (full-text search and archives, free).
- Content: each fund's Investment Objective and principal strategies section, written in a standard labelled format. The search returned one hit: a 2021 O'Shaughnessy filing says the adviser may change the strategy characteristics without notice, which means stated strategy can lag actual holdings. That lag is itself a label.
- Commercial route: sec-api.io offers an N-1A corpus, described as about 38,987 records (about 975 MB) from 1994, updated daily. CLAIM from vendor page. Licence and price unverified.
- Use for us: the purpose text paired with N-PORT holdings. This is the most direct stated-purpose pair in US public data. The gap is that no free, cleaned, text-plus-holdings join was found. We would build it.

**SEC Financial Statement Data Sets** (EVIDENCE, primary source)
- Link: https://www.sec.gov/data/financial-statement-data-sets
- Content: numeric face-financial data from XBRL filings, updated quarterly. The SEC says extraction errors are possible. A companion Financial Statement and Notes dataset exists.
- Licence: public domain per a catalogue mirror; verify.
- Use for us: fundamentals context for a holdings or strategy record. Low priority for the endorsement signal, but useful as covariates (leverage, size).

**Robotic Investment Portfolios** (TIB service; CLAIM on description, verify)
- Link: https://service.tib.eu/ldmservice/dataset/robotic-investment-portfolios
- Content as described: 18 months of daily portfolios from robo-advisory systems. This is the one found dataset with daily holdings over time for automated managers. No stated mandate field was confirmed.
- Licence: unverified.
- Use for us: a holdings time series to test the drift model. We would have to supply the purpose from the advisor's public description.

## 2. Misconduct and mandate breaches

**SEC administrative proceedings (primary) and mirrors** (EVIDENCE for the primary source; mirror status varies)
- Primary: https://www.sec.gov/litigation/admin
- Free mirror: https://huggingface.co/datasets/emperor-mew/sec-admin-proceedings. The page seen returned an empty dataset, so its contents must be checked. Its card says most adviser-misconduct cases settle as administrative proceedings, and it tags Advisers Act (IA) records.
- Also: https://api.ai-analytics.org/datasets/sec-admin-proceedings (AI Analytics, which says it derives from the SEC site).
- Paid: sec-api.io enforcement actions database (JSON, from 1997). CLAIM.
- Use for us: the labelled-breach side. Order text often states the rule breached and the conduct, for example exceeding investment restrictions. We would extract breach type and the restriction text, then match it to the fund's N-1A restrictions. No dataset tags fiduciary breach directly, so this needs a classifier. Many orders are narrative, so the label set would be small.

**SEC litigation releases** (EVIDENCE via AI Analytics technical note): covers only federal court actions. Pair with the admin set.

**NYU SEED** (EVIDENCE, academic): covers SEC actions against public companies and their subsidiaries, with allegation tags. Investment adviser and investment company allegations were 27 percent of FY2025 actions. It does not cover non-public advisers, so it fits poorly here.

**OpenSanctions "harmed investors" dataset** (EVIDENCE of the dataset, CLAIM on coverage): SEC actions with financial judgments ordered, updated daily. Commercial use needs a licence.

**FINRA BrokerCheck and disciplinary actions** (CLAIM on access state)
- Link: https://www.finra.org/investors/learn-to-invest/choosing-investment-professional/about-brokercheck/faq
- Content: disciplinary actions from 2005 onwards. The FAQ implies record-by-record access, through docket links with terms. A 2012 report says FINRA blocked automated screen scraping. A 2017 hearing raised bulk release, and no later bulk release was found.
- Licence and terms: scraping is restricted. Treat as not usable for bulk without a written licence. OpenSanctions has a FINRA actions dataset, last processed 2024-11-02, with a licence requirement for commercial use.
- Use for us: broker-level misconduct labels. Low fit for portfolio mandates.

**FCA Final Notices and ESMA sanctions** (CLAIM for the state of access)
- No official machine-readable bulk export of FCA Final Notices was found. A vendor says the FCA publishes them as PDFs whose URL format has changed several times since 2017. Verify on fca.org.uk.
- Academic: a Bangor University dataset converts FSA and FCA Final Notices from PDF into data for 2002 to 2018 (EVIDENCE, dated).
- Commercial: NexGenData sells structured FCA enforcement records on Apify, from about $250 per 1,000 records (CLAIM, price on vendor page).
- ESMA register of entities sanctioned by national authorities, via OpenSanctions: free for non-commercial use; a business licence is required.
- Use for us: UK and EU breach labels. Lower priority than the SEC set, but useful for a cross-jurisdiction check on the labels.

**AAER database** (EVIDENCE for the research database; sec-api.io and Audit Analytics are commercial access points): accounting and auditing releases. Limited to accounting fraud, so it is a weak fit for mandate breaches.

## 3. Order and market data

**LOBSTER** (EVIDENCE of the product; licence restricted)
- Link: https://vdc.univie.ac.at/data-access/lobster
- Content: reconstructed NASDAQ limit order book messages. The page indicates open access for University of Vienna members, and outside users must sign up through the provider.
- Use for us: microstructure calibration only. It does not carry purpose labels.

**FI-2010** (EVIDENCE, CC BY 4.0 per the Research.fi and etsin records)
- Link: https://etsin.fairdata.fi/dataset/73eb48d7-4dbc-4a10-a52a-da745b47a649
- Content: five Nordic stocks (Kesko, Outokumpu, Sampo, Rautaruukki, Wärtsilä), 10 trading days in June 2010, preprocessed limit order book features. A benchmark study notes the original book cannot be fully backtracked.
- Use for us: a pure model-architecture benchmark for order-book features. Not useful for the endorsement signal.

**Binance public data** (EVIDENCE for the repository; free)
- Link: https://github.com/binance/binance-public-data and downloads from data.binance.vision.
- Content: kline, trade and aggTrade files, daily or monthly, with checksum files. SPOT data from 1 January 2025 uses microsecond timestamps.
- Use for us: market context only. It carries no purpose or owner data.

**Tardis free tier** (not verified; the search returned nothing on it). Check directly before relying on it.

**Databento samples and NYSE TAQ academic options** (not searched in this pass).

## 4. Fundamentals and text

**EDGAR-CORPUS** (not verified in this pass). The search returned no source on licence or content. Verify on its original repository or paper before relying on it.

**FNSPID** (EVIDENCE: KDD 2024 paper arXiv:2402.06698, CC BY 4.0 per the arXiv licence label)
- Link: https://github.com/Zdong104/FNSPID_Financial_News_Dataset; original on Hugging Face at Zihan1004/FNSPID.
- Content: 4,775 S&P 500 companies, 1999 to 2023, about 29.7 million price records and about 15.7 million time-aligned news records, from four news sites. Price and news tables join on ticker and date. A mirror card reports a different news count (over 10 million), so the official card is the authority.
- Use for us: news-to-action context for a stock-level signal. Its link to purpose is indirect (it has no mandate), so it is a covariate source.

**Fino1 and FinCoT** (EVIDENCE: arXiv:2502.08127, NeurIPS 2025)
- Link: https://huggingface.co/datasets/TheFinAI/Fino1_Reasoning_Path_FinQA (and the FinCoT card).
- Content: financial chain-of-thought data distilled from FinQA, TATQA, DocMath-Eval, Econ-Logic, BizBench-QA and DocFinQA, with GPT-4o-generated reasoning paths. Licence varies by source; Econ-Logic is non-commercial only.
- Use for us: instruction and reasoning style for a small model; no behavioural labels.

**FinSearchComp** (EVIDENCE: paper; 635 questions)
- Link: https://huggingface.co/datasets/ByteSeedXpert/FinSearchComp
- Use for us: a financial search and reasoning benchmark. Not a purpose dataset.

**FinGPT** (not verified). The search found no 2026 update. Check the FinGPT GitHub and Hugging Face organisation directly.

**FinQA** (2021 release, known, not checked in this pass).

**CLEF 2026 Task 3 trading data** (CLAIM, from a participant's paper): TheFinAI/CLEF_Task3_Trading on Hugging Face, inside the MBZUAI/finmmevallab collection. A benchmark input set, not a log of agent decisions.

## 5. Agent trading trajectories and benchmarks

**MoltApp / molt-benchmark** (CLAIM until the card is read in full)
- Link: https://huggingface.co/datasets/patruff/molt-benchmark
- Content per the search snippet: agent reasoning, confidence and predicted outcome, paired with the actual result and automated quality scores; buy, sell and hold actions. This is the closest match found to per-decision records with reasons. Licence and score validity unverified.
- Use for us: a candidate for (action, reason, outcome) triples. The reason field is the one we want to check for stated-purpose alignment.

**QuantArena artifacts** (EVIDENCE of artifact, 2026 submission to the NeurIPS Evaluations and Datasets track)
- Link: https://huggingface.co/datasets/NIPS26Repo/quantarena-artifacts
- Content: daily portfolio state, trade log, and pre-computed metrics for backtests. The card warns that for the default backend the trade justification field is mostly short bookkeeping text, so the reasoning signal is thin.
- Use for us: holdings-over-time for a simulated agent, with weak reasons. Good for drift, weak for endorsement.

**KTD-Fin** (EVIDENCE: arXiv:2605.28359, submitted 27 May 2026, Zhu et al.)
- Link: https://arxiv.org/abs/2605.28359
- Content: a memory-controlled benchmark for LLM trading agents on the CSI300, with a masking protocol to block memorised data and a Barra-style attribution of returns into market, style and selection alpha. Reported finding: ten frontier agents' returns are mostly explained by market and style exposure, and nine of ten show negative factor-adjusted selection alpha. Secondary write-ups repeat this; check the paper.
- Release: the paper says it will release the environment, scripts, protocols and full evaluation data. Repository and licence not found.
- Use for us: attribution labels that separate what an agent was doing (style) from what it claimed to be doing (selection). That is close to a drift label.

**StockBench** (EVIDENCE: arXiv:2510.02209, v2 revised 2 March 2026)
- Link: https://arxiv.org/abs/2510.02209. Project page stockbench.github.io (from search; not fetched).
- Content: multi-month back-trading on March to July 2025 market data; open source; the authors plan continuous updates. Hugging Face status unconfirmed.

**AI-Trader** (EVIDENCE: arXiv:2512.10971; code and evaluation data on GitHub at HKUDS/AI-Trader)
- Content: a live, uncontaminated evaluation of autonomous agents. Licence unverified.

**InvestorBench** (EVIDENCE: arXiv:2412.18174, ACL 2025; project page suchow.io/investorbench)
- Content: a multi-task financial decision benchmark for LLM agents. Hugging Face dataset not confirmed.

**AlphaForgeBench** (EVIDENCE: arXiv:2602.18481, accepted to KDD 2026)
- Content: LLMs write alpha factors and strategy code rather than trade actions. The authors argue direct trading agents show high run-to-run variance. Use only for the code-as-policy angle.

**Alpha Arena (nof1.ai)** (CLAIM: press and competition pages)
- Season 1 ran 10 October to 3 November 2025 on Hyperliquid crypto with six models; Season 1.5 covered US equities; Season 2 was announced.
- Public trade logs are said to exist, and third-party GitHub trackers aggregate them. No official bulk export was found. Check nof1.ai directly; licence unknown.
- Use for us: per-model trades with visible reasoning, but no owner purpose. The prompt may carry a strategy, which would be the purpose proxy.

**DX Terminal Pro and DXAP fleet** (EVIDENCE: Hugging Face paper page 2609.05663, September 2026; WebFetch read on 2026-11-19)
- Link: https://huggingface.co/papers/2609.05663; public artifacts at dxrg.ai/research.
- Content as summarised by the fetch: about six months of production records. DX Terminal Pro covered 3,505 user-funded vaults trading ETH on Base for 21 days (February and March 2026), with 7.5 million model calls and about 300 thousand onchain actions. The DXAP fleet covered about 500 to 599 user-created agents trading Hyperliquid perpetuals (June to August 2026), with about 232 thousand multi-tool turns and 14.6 thousand fills.
- Licence: none stated. Raw DXAP telemetry holds user identifiers and is only available as aggregates.
- Use for us: the closest structure to owner-funded agents with a per-agent configuration. The stated purpose would be the vault or agent configuration. The raw data is not available in full.

## 6. Robo-advisor and retail portfolio datasets

**ILS-Bench** (EVIDENCE of the dataset on Mendeley Data; synthetic)
- Link: https://data.mendeley.com/datasets/w48mh2dtg5/1
- Content: a suitability benchmark mapping investor language to risk tolerance and risk capacity. It is close to an investment policy statement elicitation task.
- Use for us: converting a client's stated profile into a suitability label. Synthetic, so calibrate with care.

**Robo-advisor adoption datasets, April 2026** (EVIDENCE on Mendeley Data; respondent-level)
- Links: https://data.mendeley.com/datasets/39rw5ywj8r/1 and https://data.mendeley.com/datasets/4c298v4yv9
- Content: randomised experiment and survey data on robo-advisor trust and adoption. No holdings. Not useful for behaviour labels.

**Investment policy statements** (no public corpus found). Most search results were low-quality template pages. Form ADV Part 2A brochures from the SEC's adviser database are the likely public proxy for stated strategy; not searched in this pass.

## 7. Kaggle, Hugging Face and X

- Hugging Face: the finance-related items above are the main hits. The Finance-Agentic-AI/Portfolio-Management dataset appeared in search; its card was not read.
- Kaggle: not searched in this pass.
- X and practitioner posts: no open dataset of AI-agent fund holdings released in 2026 was found. Relevant items are commercial: X's Cashtags (April 2026, US and Canada), and BridgeWise's SentimentWise, an API product built on X data (announced 29 April 2026). CLAIM. Virat Singh's Dexter (an open-source multi-agent finance system) and the findatasets project were mentioned; their datasets were not checked. CLAIM.

---

## Summary of fit

The strongest stated-purpose and holdings pair in public data is US fund objectives (N-1A text) with N-PORT holdings. The strongest labelled-breach source is SEC administrative proceedings. The strongest per-decision reasons are in agent benchmarks, but the reasons are thin or unverified. No single existing dataset carries (stated purpose, actions, match or drift, reason). Building the join is the work.

## Beyond what they asked

Places where a stated purpose and actual behaviour both exist and can be matched, which nobody here uses for this today:

1. Form ADV Part 2A brochures (the adviser's stated strategy and client restrictions) matched to the same firm's Form 13F and public fund holdings. The brochure is a written purpose; the holdings are behaviour.
2. Owner-funded DeFi vaults and user-built Hyperliquid agents (the DX Terminal Pro records). The owner's configuration is the purpose; onchain fills are the behaviour. Ask for the configuration, not only the aggregates.
3. DAO treasury policies and governance proposals (Snapshot or Tally) matched to executed wallet transfers on Etherscan or Dune. A passed proposal is a stated mandate; the transfers are behaviour.
4. Pine Script and TradingView strategy descriptions published with the code, matched to the same author's live or backtest trades where the author publishes them.
5. Form 990 and Schedule D of US charities and endowments, which describe investment policy and list holdings. Purpose text plus holdings, annual, public, unverified in this pass.
6. Form N-CEN (sub-adviser and index or actively managed status) joined to N-PORT. Labels for whether a fund is still doing what its registration says.
7. Fund board minutes and shareholder proxy statements that record a change of strategy, matched to the N-PORT holdings change that followed. The change is a dated stated-purpose event.
8. Court and regulatory complaints that quote a mandate breach, matched to the trade log that the complaint cites. Each complaint is a labelled breach with its own evidence.

Next steps, if the lab wants them: check the N-PORT granularity on sec.gov; read the molt-benchmark and KTD-Fin cards for licence and record schema; pull the admin proceedings mirror and confirm contents; ask the DX Terminal authors for the vault configuration fields; and draft the N-1A to N-PORT join on a single small fund family as a feasibility test.
