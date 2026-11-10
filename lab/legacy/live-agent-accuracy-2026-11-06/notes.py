import json,re,time,sys,urllib.request
from concurrent.futures import ThreadPoolExecutor
KEY=[l.split("=",1)[1].strip().strip('"\'') for l in open(__import__("os").environ["OG_ENV_FILE"]) if l.startswith("OPENROUTER_API_KEY=")][0]
F=json.load(open("facts.json"))
LATEST={"AAPL":"2026-09-26","MSFT":"2026-06-30","NVDA":"2026-01-25","COST":"2026-08-30","WMT":"2026-01-31","INTC":"2025-12-27","HD":"2026-02-01","BA":"2025-12-31","AMZN":"2025-12-31","GOOGL":"2025-12-31"}
NAME={"AAPL":"Apple","MSFT":"Microsoft","NVDA":"NVIDIA","COST":"Costco","WMT":"Walmart","INTC":"Intel","HD":"The Home Depot","BA":"Boeing","AMZN":"Amazon","GOOGL":"Alphabet"}
METRICS="revenue, net_income, eps_diluted, operating_income, operating_cash_flow, operating_margin_pct, net_margin_pct, revenue_growth_pct"
SYS=("Today is 2026-11-06. You are an equity research analyst. Research the company's latest two reported fiscal years and write a short research note "
     "(about 150 words) that uses at least 8 specific reported figures. Then list every figure you used. Allowed metrics: "+METRICS+". "
     "Money in USD millions, EPS in USD per share, percentages as percent. fiscal_year_end is the period end date of that fiscal year. "
     'Reply with JSON only: {"note": "...", "figures": [{"metric": "...", "fiscal_year_end": "YYYY-MM-DD", "value": <number>, "quote": "<the words in the note>"}]}')
def call(model,t):
    body={"model":model,"messages":[{"role":"system","content":SYS},{"role":"user","content":f"Company: {NAME[t]} ({t})"}],"max_tokens":16000,"usage":{"include":True},"plugins":[{"id":"web","max_results":8}]}
    for a in range(3):
        try:
            d=json.load(urllib.request.urlopen(urllib.request.Request("https://openrouter.ai/api/v1/chat/completions",data=json.dumps(body).encode(),headers={"Authorization":"Bearer "+KEY,"Content-Type":"application/json"}),timeout=300)); break
        except Exception as e: d=None; time.sleep(3)
    rec={"model":model,"t":t}
    if not d or "choices" not in d: rec["error"]=True; return rec
    txt=d["choices"][0]["message"].get("content") or ""; rec["cost"]=d.get("usage",{}).get("cost",0)
    m=re.search(r"\{.*\}",txt,re.S)
    try: rec["out"]=json.loads(m.group(0))
    except Exception: rec["out"]=None; rec["raw"]=txt[:400]
    return rec
models=sys.argv[1].split(",")
with ThreadPoolExecutor(10) as p: res=list(p.map(lambda j:call(*j),[(m,t) for m in models for t in LATEST]))
json.dump(res,open("notes_res.json","w"),indent=1)
print(len(res),"notes, cost $%.3f"%sum(r.get("cost",0) or 0 for r in res),"failed",sum(1 for r in res if not r.get("out")))
