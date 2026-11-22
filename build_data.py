"""Build JSON expected by the existing index.html; report FINRA timing limitations."""
from pathlib import Path
import json,subprocess,sys
import pandas as pd
ROOT=Path(__file__).resolve().parent
p=subprocess.run([sys.executable,str(ROOT/'market_heat.py')],cwd=ROOT,capture_output=True,text=True)
print(p.stdout,flush=True)
if p.stderr: print(p.stderr,file=sys.stderr,flush=True)
if p.returncode: raise SystemExit(p.returncode)
d=pd.read_csv(ROOT/'heat_history.csv')
cols=['date','heat','equity_pc','total_pc','margin','liquidity','fomo','tw_close','tw_drawdown','signal']
for c in cols:
    if c not in d.columns: d[c]=None
for c in cols[1:-1]: d[c]=pd.to_numeric(d[c],errors='coerce')
rows=json.loads(d[cols].to_json(orient='records',date_format='iso'))
valid=d.dropna(subset=['heat'])
events=pd.read_csv(ROOT/'bottom_events.csv')
quality=(ROOT/'margin_quality.txt').read_text(encoding='utf-8').strip()
backtest={}
for h in (5,20,60):
    key=f'tw_fwd_{h}d'
    v=pd.to_numeric(events[key],errors='coerce').dropna() if key in events else pd.Series(dtype=float)
    # Avoid presenting estimated historical FINRA release dates as a validated backtest.
    if quality!='verified':
        backtest[str(h)]={'n':0,'win_rate':None,'avg_return':None}
    else:
        backtest[str(h)]={'n':int(len(v)),'win_rate':float((v>0).mean()) if len(v) else None,'avg_return':float(v.mean()) if len(v) else None}
latest=valid.iloc[-1]['date'] if len(valid) else None
note=('僅供研究；FINRA 使用統計月底後45日的保守估計可用日，非歷史實際公布日。'
      '因此熱度及訊號屬暫行估計，歷史回測暫不提供。FRED 歷史值可能經修訂。'
      if quality=='estimated_45d' else
      '僅供研究；FINRA 依提供的公布日資料對齊。仍需驗證公布日來源；FRED 歷史值可能經修訂。')
payload={'generated_at':pd.Timestamp.now(tz='UTC').isoformat(),
         'latest_complete_date':latest,
         'weights':{'equity_pc':25,'total_pc':15,'margin':15,'liquidity':20,'fomo':25},
         'history':rows,'backtest':backtest,'margin_date_quality':quality,'note':note}
folder=ROOT/'data';folder.mkdir(exist_ok=True)
(folder/'dashboard.json').write_text(json.dumps(payload,ensure_ascii=False,separators=(',',':'),allow_nan=False),encoding='utf-8')
print(f'dashboard.json: {len(rows)} rows; latest complete {latest}; FINRA date quality={quality}')
