import json
F=json.load(open("facts.json"))
def v(t,m,end): return F[t][m][end]["v"]
def prev(t,m,end):
    ends=sorted(F[t][m]); i=ends.index(end); return ends[i-1]
Q=[]
def add(id,q,kind,ans,unit,wrong_period=None): Q.append(dict(id=id,q=q,kind=kind,answer=ans,unit=unit,wrong_period=wrong_period))
M=1e6
add("AAPL-rev-FY26","What were Apple's total net sales for fiscal year 2026 (the year ended September 26, 2026)?","fresh lookup",v("AAPL","revenue","2026-09-26")/M,"USD millions",v("AAPL","revenue","2025-09-27")/M)
add("AAPL-eps-FY25","What was Apple's diluted earnings per share for fiscal year 2025 (ended September 27, 2025)?","lookup",v("AAPL","eps_diluted","2025-09-27"),"USD per share",v("AAPL","eps_diluted","2024-09-28"))
add("MSFT-rev-FY26","What was Microsoft's total revenue for fiscal year 2026 (ended June 30, 2026)?","lookup",v("MSFT","revenue","2026-06-30")/M,"USD millions",v("MSFT","revenue","2025-06-30")/M)
add("MSFT-opinc-FY26","What was Microsoft's operating income for fiscal year 2026 (ended June 30, 2026)?","lookup",v("MSFT","op_income","2026-06-30")/M,"USD millions",v("MSFT","op_income","2025-06-30")/M)
add("NVDA-ni-FY26","What was NVIDIA's net income for its fiscal year 2026?","naming trap",v("NVDA","net_income","2026-01-25")/M,"USD millions",v("NVDA","net_income","2025-01-26")/M)
r1,r0=v("NVDA","revenue","2026-01-25"),v("NVDA","revenue","2025-01-26")
add("NVDA-growth-FY26","By what percentage did NVIDIA's revenue grow in fiscal year 2026 compared with fiscal year 2025?","calculation",100*(r1/r0-1),"percent",100*(r0/v("NVDA","revenue","2024-01-28")-1))
add("COST-opm-FY26","What was Costco's operating margin (operating income divided by total revenue) for fiscal year 2026 (ended August 30, 2026)?","calculation",100*v("COST","op_income","2026-08-30")/v("COST","revenue","2026-08-30"),"percent",100*v("COST","op_income","2025-08-31")/v("COST","revenue","2025-08-31"))
add("WMT-rev-FY26","What were Walmart's total revenues for its fiscal year 2026?","naming trap",v("WMT","revenue","2026-01-31")/M,"USD millions",v("WMT","revenue","2025-01-31")/M)
add("INTC-ni-FY25","What was Intel's net income (loss) attributable to Intel for fiscal year 2025?","sign trap",v("INTC","net_income","2025-12-27")/M,"USD millions",v("INTC","net_income","2024-12-28")/M)
add("HD-ni-FY25","What were The Home Depot's net earnings for fiscal 2025 (the year ended February 1, 2026)?","lookup",v("HD","net_income","2026-02-01")/M,"USD millions",v("HD","net_income","2025-02-02")/M)
add("HD-eps-FY25","What were The Home Depot's diluted earnings per share for fiscal 2025 (the year ended February 1, 2026)?","lookup",v("HD","eps_diluted","2026-02-01"),"USD per share",v("HD","eps_diluted","2025-02-02"))
b1,b0=v("BA","revenue","2025-12-31"),v("BA","revenue","2024-12-31")
add("BA-growth-2025","By what percentage did Boeing's total revenues change in 2025 compared with 2024?","calculation",100*(b1/b0-1),"percent",100*(b0/v("BA","revenue","2023-12-31")-1))
add("AMZN-ocf-2025","What was Amazon's net cash provided by operating activities for 2025?","lookup",v("AMZN","ocf","2025-12-31")/M,"USD millions",v("AMZN","ocf","2024-12-31")/M)
add("GOOGL-eps-2025","What was Alphabet's diluted earnings per share for 2025?","lookup",v("GOOGL","eps_diluted","2025-12-31"),"USD per share",v("GOOGL","eps_diluted","2024-12-31"))
json.dump(Q,open("questions.json","w"),indent=1)
for q in Q: print(q["id"],q["kind"],round(q["answer"],2),q["unit"],"| prev-year",round(q["wrong_period"],2))
