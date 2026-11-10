import json,collections,datetime as dt
F=json.load(open("facts.json")); res=json.load(open("notes_res.json"))
BASE={"revenue":"revenue","net_income":"net_income","eps_diluted":"eps_diluted","operating_income":"op_income","operating_cash_flow":"ocf"}
def ends(t,m): return sorted(F[t][m])
def nearest(t,m,e):
    # the 10-K period whose end is within 10 days of the stated end
    try: d=dt.date.fromisoformat(e)
    except Exception: return None
    for k in ends(t,m):
        if abs((dt.date.fromisoformat(k)-d).days)<=10: return k
def truth(t,metric,e):
    if metric in BASE:
        k=nearest(t,BASE[metric],e); return (F[t][BASE[metric]][k]["v"]/(1 if metric=="eps_diluted" else 1e6), k) if k else (None,None)
    k=nearest(t,"revenue",e)
    if not k: return None,None
    r=F[t]["revenue"][k]["v"]
    if metric=="operating_margin_pct" and k in F[t]["op_income"]: return 100*F[t]["op_income"][k]["v"]/r,k
    if metric=="net_margin_pct" and k in F[t]["net_income"]: return 100*F[t]["net_income"][k]["v"]/r,k
    if metric=="revenue_growth_pct":
        e2=ends(t,"revenue"); i=e2.index(k)
        if i: return 100*(r/F[t]["revenue"][e2[i-1]]["v"]-1),k
    return None,None
def close(metric,x,a,quote):
    if metric.endswith("_pct"): return abs(x-a)<=0.5
    if metric=="eps_diluted": return abs(x-a)<=0.02
    return abs(x-a)<=0.005*abs(a)+1      # stated to within 0.5%
tab=collections.defaultdict(collections.Counter); bad=[]; notes_with_err=collections.Counter(); notes=collections.Counter()
for r in res:
    if not r.get("out"): continue
    m=r["model"].split("/")[1]; notes[m]+=1; err=False
    for f in r["out"].get("figures",[]):
        try: x=float(f["value"])
        except Exception: tab[m]["unparsed"]+=1; continue
        a,k=truth(r["t"],f.get("metric",""),f.get("fiscal_year_end",""))
        if a is None: tab[m]["no filing match"]+=1; continue
        if close(f["metric"],x,a,f.get("quote","")): tab[m]["right"]+=1
        else:
            tab[m]["wrong"]+=1; err=True; bad.append((m,r["t"],f["metric"],k,round(x,2),round(a,2),f.get("quote","")[:70]))
    notes_with_err[m]+=err
for m in tab: print(m,dict(tab[m]),"| notes with at least one wrong figure: %d of %d"%(notes_with_err[m],notes[m]))
print(); [print(b) for b in bad]
