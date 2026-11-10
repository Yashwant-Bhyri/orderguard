import json,sys,glob,collections
Q={q["id"]:q for q in json.load(open(__import__("os").environ.get("QF","questions.json")))}
res=[r for f in sys.argv[1:] for r in json.load(open(f))]
def num(a):
    try: return float(str(a.get("value")).replace(",","")) if a and a.get("value") is not None else None
    except Exception: return None
def norm(q,x,unit):
    # accept billions if the model said so
    if x is None: return None
    if q["unit"]=="USD millions" and unit and "billion" in unit.lower(): x*=1000
    return x
def ok(q,x):
    if x is None: return False
    a=q["answer"]
    if q["unit"]=="percent": return abs(x-a)<=0.3
    if q["unit"]=="USD per share": return abs(x-a)<=0.02
    return abs(x-a)<=0.005*abs(a)+1
def grade(r):
    q=Q[r["id"]]
    if "error" in r: return "error",None
    x=norm(q,num(r.get("ans")),(r.get("ans") or {}).get("unit",""))
    if x is None: return "no answer",x
    if ok(q,x): return "right",x
    if ok({**q,"answer":q["wrong_period"]},x): return "wrong year",x
    return "wrong",x
tab=collections.defaultdict(collections.Counter); cost=collections.Counter()
for r in res:
    g,x=grade(r); r["grade"]=g; r["x"]=x; tab[(r["model"],r["mode"])][g]+=1; cost[(r["model"],r["mode"])]+=r.get("cost") or 0
print("%-34s %-6s %5s %5s %6s %5s %5s %7s"%("model","mode","right","wrong","wr-yr","none","err","cost$"))
for k in sorted(tab):
    c=tab[k]; print("%-34s %-6s %5d %5d %6d %5d %5d %7.3f"%(k[0],k[1],c["right"],c["wrong"],c["wrong year"],c["no answer"],c["error"],cost[k]))
if "-v" in sys.argv[0:1] or True:
    by=collections.defaultdict(list)
    for r in res: by[r["id"]].append(r)
    print()
    for i,q in Q.items():
        print(f"{i} [{q['kind']}] truth {q['answer']:.2f}: "+"; ".join(f"{r['model'].split('/')[1][:14]}/{r['mode'][0]}={'%.2f'%r['x'] if r['x'] is not None else '-'}{'' if r['grade']=='right' else '✗' if r['grade']!='wrong year' else '✗yr'}" for r in sorted(by[i],key=lambda r:(r['model'],r['mode']))))
json.dump(res,open("graded.json","w"),indent=1)
