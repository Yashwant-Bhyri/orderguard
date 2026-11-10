import json,urllib.request,datetime as dt,os
UA={"User-Agent":"OrderGuardVerify research-prototype unaffiliated"}
CIK={"AAPL":320193,"MSFT":789019,"NVDA":1045810,"COST":909832,"WMT":104169,"INTC":50863,"HD":354950,"BA":12927,"AMZN":1018724,"GOOGL":1652044}
TAGS={"revenue":["Revenues","RevenueFromContractWithCustomerExcludingAssessedTax","SalesRevenueNet"],"net_income":["NetIncomeLoss"],"eps_diluted":["EarningsPerShareDiluted"],"op_income":["OperatingIncomeLoss"],"ocf":["NetCashProvidedByUsedInOperatingActivities"]}
out={}
for t,c in CIK.items():
    p=f"cf_{t}.json"
    if not os.path.exists(p):
        r=urllib.request.urlopen(urllib.request.Request(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{c:010d}.json",headers=UA),timeout=60); open(p,"wb").write(r.read())
    d=json.load(open(p))["facts"]["us-gaap"]
    out[t]={}
    for m,tags in TAGS.items():
        best={}
        for tag in tags:
            if tag not in d: continue
            for u,rows in d[tag]["units"].items():
                for x in rows:
                    if x.get("form")!="10-K" or "start" not in x: continue
                    days=(dt.date.fromisoformat(x["end"])-dt.date.fromisoformat(x["start"])).days
                    if not 350<=days<=380: continue
                    k=x["end"]
                    # latest filed wins; first tag in list preferred when both exist for same end
                    if k not in best or (x["filed"]>best[k]["filed"] and best[k]["tag"]==tag): best[k]={"v":x["val"],"filed":x["filed"],"tag":tag,"start":x["start"]}
        out[t][m]=best
json.dump(out,open("facts.json","w"))
for t in out:
    ends=sorted(out[t]["revenue"])[-3:]
    print(t,[(e,round(out[t]["revenue"][e]["v"]/1e9,3),out[t]["revenue"][e]["filed"]) for e in ends])
