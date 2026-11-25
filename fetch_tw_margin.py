import csv, json, re, time, argparse, urllib.request, urllib.parse, urllib.error
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from pathlib import Path

PATH = Path(__file__).resolve().parent / 'tw_margin.csv'
URL = 'https://www.twse.com.tw/rwd/zh/marginTrading/MI_MARGN'

def parse(j, day):
    if j.get('stat') != 'OK':
        if any(s in str(j.get('stat','')) for s in ('沒有','查無','無資料')): return None
        raise ValueError('Unexpected status: '+str(j.get('stat')))
    if str(j.get('date','')) != day.strftime('%Y%m%d'): raise ValueError('Response date mismatch')
    groups = [j.get('creditList',[])] + [t.get('data',[]) for t in j.get('tables',[]) if isinstance(t,dict)]
    for rows in groups:
        for r in rows:
            if isinstance(r,list) and len(r)==6 and re.sub(r'\s','',str(r[0])).replace('（','(').replace('）',')') in ('融資金額(仟元)','融資金額(千元)'):
                v=int(str(r[5]).replace(',','').strip())
                if v<=0: raise ValueError('Invalid balance')
                return v
    raise ValueError('Margin amount row missing')

def main():
    p=argparse.ArgumentParser(); p.add_argument('--limit',type=int,default=15); a=p.parse_args()
    if not 1<=a.limit<=30: p.error('limit must be 1–30')
    data={}
    if PATH.exists():
        with PATH.open(encoding='utf-8-sig') as f:
            for r in csv.DictReader(f): data[r['date']]=int(r['margin_balance'])
    today=datetime.now(ZoneInfo('Asia/Taipei')).date(); count=0; failed=False
    try:
        for i in range(100):
            if count>=a.limit: break
            day=today-timedelta(days=i); key=day.isoformat()
            if day.weekday()>=5 or (key in data and i>=7): continue
            if count: time.sleep(10)
            count+=1
            try:
                q=urllib.parse.urlencode({'date':day.strftime('%Y%m%d'),'selectType':'MS','response':'json'})
                req=urllib.request.Request(URL+'?'+q,headers={'User-Agent':'MarketResearch/1.0','Accept':'application/json'})
                with urllib.request.urlopen(req,timeout=25) as r: j=json.load(r)
                v=parse(j,day)
                if v is not None: data[key]=v
                print(key,v,flush=True)
            except Exception as e:
                print(key,e,flush=True); failed=True; break
    finally:
        if data:
            tmp=PATH.with_suffix('.tmp')
            with tmp.open('w',encoding='utf-8',newline='') as f:
                w=csv.writer(f); w.writerow(['date','margin_balance']); w.writerows(sorted(data.items()))
            tmp.replace(PATH)
        print('Total rows:',len(data))
    if failed or not data: raise SystemExit(1)
if __name__=='__main__': main()
