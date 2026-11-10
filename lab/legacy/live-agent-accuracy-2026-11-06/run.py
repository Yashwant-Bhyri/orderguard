import json,re,time,sys,urllib.request
from concurrent.futures import ThreadPoolExecutor
KEY=[l.split("=",1)[1].strip().strip('"\'') for l in open(__import__("os").environ["OG_ENV_FILE"]) if l.startswith("OPENROUTER_API_KEY=")][0]
MODELS=sys.argv[1].split(",")
MODES=sys.argv[2].split(",")
Q=json.load(open("questions.json"))
SYS=("Today is 2026-11-06. Answer the question about a US-listed company's reported results with one number. "
     "Give money amounts in USD millions, per-share amounts in USD per share, and percentages as percent (e.g. 12.3). "
     'Reply with JSON only: {"value": <number or null if you cannot answer>, "unit": "...", "fiscal_period_end": "YYYY-MM-DD", "source": "<where the figure comes from>"}')
def call(model,mode,q):
    body={"model":model,"messages":[{"role":"system","content":SYS},{"role":"user","content":q["q"]}],"max_tokens":12000,"usage":{"include":True}}
    if mode=="web": body["plugins"]=[{"id":"web","max_results":5}]
    t0=time.time()
    for attempt in range(3):
        try:
            r=urllib.request.urlopen(urllib.request.Request("https://openrouter.ai/api/v1/chat/completions",data=json.dumps(body).encode(),headers={"Authorization":"Bearer "+KEY,"Content-Type":"application/json"}),timeout=240)
            d=json.load(r); break
        except Exception as e:
            err=str(e)[:200]; d=None; time.sleep(3)
    rec={"model":model,"mode":mode,"id":q["id"],"secs":round(time.time()-t0,1)}
    if not d or "choices" not in d: rec.update(error=(d or {}).get("error") if d else err); return rec
    msg=d["choices"][0]["message"]; txt=msg.get("content") or ""
    rec["cost"]=d.get("usage",{}).get("cost",0); rec["raw"]=txt[:600]
    rec["urls"]=[a.get("url_citation",{}).get("url") for a in (msg.get("annotations") or []) if a.get("type")=="url_citation"][:6]
    m=re.search(r"\{.*\}",txt,re.S)
    try: rec["ans"]=json.loads(m.group(0))
    except Exception: rec["ans"]=None
    return rec
jobs=[(m,mo,q) for m in MODELS for mo in MODES for q in Q]
with ThreadPoolExecutor(10) as p: res=list(p.map(lambda j:call(*j),jobs))
out=f"res_{int(time.time())}.json"; json.dump(res,open(out,"w"),indent=1)
print(out,len(res),"calls, cost $%.3f"%sum(r.get("cost",0) or 0 for r in res),"errors",sum("error" in r for r in res))
for r in res:
    if "error" in r: print("ERR",r["model"],r["mode"],r["id"],str(r["error"])[:150])
