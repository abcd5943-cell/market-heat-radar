"""Prospective shadow model; no changes to production heat."""
import json, math, datetime as dt, itertools
from pathlib import Path
D=Path('data'); D.mkdir(exist_ok=True)
K=['equity_pc','total_pc','margin','liquidity','fomo']; BASE=[25,15,15,20,25]
def read(p,default):
    return json.loads(p.read_text()) if p.exists() else default
def save(p,x):
    p.write_text(json.dumps(x,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
def valid(x): return isinstance(x,(int,float)) and math.isfinite(x)
def heat(x,w): return sum(a*b for a,b in zip(x,w))/100
def corr(a,b):
    if len(a)<2:return None
    x=[v-sum(a)/len(a) for v in a]; y=[v-sum(b)/len(b) for v in b]
    den=math.sqrt(sum(v*v for v in x)*sum(v*v for v in y))
    return sum(u*v for u,v in zip(x,y))/den if den else None
p=read(D/'dashboard.json',{}); rows=sorted(p.get('history',[]),key=lambda r:r['date']); today=dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).date().isoformat()
sp=D/'model_snapshots.json'; snaps=read(sp,{}); out=D/'model_validation.json'; old=read(out,{})
w=old.get('weights',BASE); month=today[:7]; last_review=old.get('last_review'); log=old.get('adjustments',[])
# Freeze first observed complete score per model date, never backfill snapshots.
complete=[r for r in rows if all(valid(r.get(k)) for k in K)]
if complete:
    r=complete[-1]; date=r['date']; age=(dt.date.fromisoformat(today)-dt.date.fromisoformat(date)).days
    if 0<=age<=7 and date not in snaps:
        snaps[date]={'observed':today,'x':[r[k] for k in K],'weights':w[:],'fixed':heat([r[k] for k in K],BASE),'dynamic':heat([r[k] for k in K],w)}
# Existing dashboard is aligned to US sessions, not a native TW calendar.
# Conservative entry: first row strictly after observation day; 20 subsequent aligned rows.
prices=[(r['date'],r['tw_close']) for r in rows if valid(r.get('tw_close')) and r['tw_close']>0 and r['date']<today]
for s in snaps.values():
    if 'return' in s:continue
    ix=next((i for i,(d,v) in enumerate(prices) if d>s['observed']),None)
    if ix is not None and ix+20<len(prices):
        s.update(entry=prices[ix][0],exit=prices[ix+20][0],**{'return':prices[ix+20][1]/prices[ix][1]-1})
mature=sorted([s for s in snaps.values() if 'return' in s],key=lambda s:s['observed'])
def metric(ss,weights=None,field=None):
    return corr([- (s[field] if field else heat(s['x'],weights)) for s in ss],[s['return'] for s in ss])
status='累積前瞻樣本'; train=[]; test=[]; candidate=None; test_base=None; test_candidate=None
# Nonoverlapping outcome intervals for conservative effective sample count.
ind=[]
for s in mature:
    if not ind or s['entry']>ind[-1]['exit']:ind.append(s)
if len(ind)>=36:
    test=ind[-12:]; train=[s for s in ind[:-12] if s['exit']<test[0]['entry']]
    if len(train)>=24:
        status='等待每月評估'
        if last_review!=month:
            last_review=month
            candidates=[list(v) for v in itertools.product(*[range(max(5,a-2),min(35,a+2)+1) for a in w]) if sum(v)==100]
            def objective(v):
                c=metric(train,v);return (c if c is not None else -2)-0.002*sum(abs(a-b) for a,b in zip(v,w))
            candidate=max(candidates,key=objective); test_base=metric(test,BASE); test_candidate=metric(test,candidate); current=metric(test,w)
            if candidate!=w and test_candidate is not None and test_base is not None and current is not None and test_candidate>max(test_base,current)+.03 and test_candidate>0:
                log.append({'date':today,'before':w,'after':candidate,'validation_correlation':test_candidate});w=candidate;status='通過門檻，微調影子模型'
            else:status='未通過門檻，維持權重'
            # If existing shadow underperforms, move toward baseline within same cap.
            if current is not None and test_base is not None and current<test_base-.03 and status.startswith('未'):
                fallback=min(candidates,key=lambda v:sum(abs(a-b) for a,b in zip(v,BASE)))
                if fallback!=w:log.append({'date':today,'before':w,'after':fallback,'reason':'向基準回退'});w=fallback;status='向固定權重回退'
latest=complete[-1] if complete else None
save(sp,snaps)
save(out,{'generated_at':today,'weights':w,'base_weights':BASE,'keys':K,'status':status,'last_review':last_review,'snapshots':len(snaps),'mature':len(mature),'independent':len(ind),'minimum_independent':36,'fixed_correlation':metric(ind,field='fixed'),'dynamic_correlation':metric(ind,field='dynamic'),'latest_date':latest['date'] if latest else None,'fixed_heat':heat([latest[k] for k in K],BASE) if latest else None,'dynamic_heat':heat([latest[k] for k in K],w) if latest else None,'adjustments':log,'note':'前瞻快照；20 個美股對齊資料列報酬代理，非精確台股交易日。相關係數非勝率；未扣成本。'})
