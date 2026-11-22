from pathlib import Path
import json, subprocess, sys
import pandas as pd
ROOT=Path(__file__).parent
p=subprocess.run([sys.executable,str(ROOT/'market_heat.py')],cwd=ROOT,capture_output=True,text=True)
print(p.stdout,p.stderr)
if p.returncode: raise SystemExit(p.returncode)
d=pd.read_csv(ROOT/'heat_history.csv')
cols=['date','heat','equity_pc','total_pc','margin','liquidity','fomo','tw_close','tw_drawdown','signal']
for c in cols:
 if c not in d: d[c]=None
for c in cols[1:-1]: d[c]=pd.to_numeric(d[c],errors='coerce')
rows=json.loads(d[cols].where(pd.notna(d[cols]),None).to_json(orient='records',date_format='iso'))
valid=d.dropna(subset=['heat'])
events=pd.read_csv(ROOT/'bottom_events.csv') if (ROOT/'bottom_events.csv').exists() else pd.DataFrame()
backtest={}
for h in (5,20,60):
 col=f'tw_fwd_{h}d'; v=pd.to_numeric(events[col],errors='coerce').dropna() if col in events else pd.Series(dtype=float)
 backtest[str(h)]={'n':int(len(v)),'win_rate':float((v>0).mean()) if len(v) else None,'avg_return':float(v.mean()) if len(v) else None}
latest=valid.iloc[-1]['date'] if len(valid) else None
payload={'generated_at':pd.Timestamp.now(tz='UTC').isoformat(),'latest_complete_date':latest,'weights':{'equity_pc':25,'total_pc':15,'margin':15,'liquidity':20,'fomo':25},'history':rows,'backtest':backtest,'note':'僅研究用途；FINRA 必須按實際公布日輸入；歷史 FRED 資料可能經修訂。'}
(ROOT/'data'/'dashboard.json').write_text(json.dumps(payload,ensure_ascii=False,separators=(',',':')),encoding='utf8')
print('dashboard.json generated:',len(rows),'rows; latest complete:',latest)
