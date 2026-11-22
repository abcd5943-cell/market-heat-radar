"""Market Heat Radar. FINRA month-end + 45 days is a CONSERVATIVE PROXY, not verified release dates."""
from pathlib import Path
import os, time
import numpy as np
import pandas as pd
import requests
import yfinance as yf
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

ROOT=Path(__file__).resolve().parent
START='2015-01-01'
WEIGHTS={'equity_pc':.25,'total_pc':.15,'margin':.15,'liquidity':.20,'fomo':.25}


def fred(series):
    key=os.environ.get('FRED_API_KEY','').strip()
    if not key: raise RuntimeError('FRED_API_KEY 未設定')
    url='https://api.stlouisfed.org/fred/series/observations'
    params={'series_id':series,'api_key':key,'file_type':'json','observation_start':START}
    for attempt in range(3):
        try:
            r=requests.get(url,params=params,timeout=(10,30)); r.raise_for_status()
            obs=r.json().get('observations',[])
            if not obs: raise ValueError('沒有觀測值')
            d=pd.DataFrame(obs)
            s=pd.Series(pd.to_numeric(d['value'],errors='coerce').to_numpy(),index=pd.to_datetime(d['date'])).dropna().sort_index()
            if s.empty: raise ValueError('沒有有效數值')
            print(f'FRED {series}: {len(s)} 筆，最後日期 {s.index[-1].date()}')
            return s
        except (requests.RequestException,ValueError) as e:
            if attempt==2: raise RuntimeError(f'FRED {series} 下載失敗: {e}') from e
            time.sleep(3*(attempt+1))


def market(symbol):
    d=yf.download(symbol,start=START,auto_adjust=True,progress=False,threads=False)
    if d.empty: raise RuntimeError(f'{symbol} 行情為空')
    if isinstance(d.columns,pd.MultiIndex): d.columns=d.columns.get_level_values(0)
    d.index=pd.to_datetime(d.index).tz_localize(None).normalize()
    return d[['Close','Volume']].dropna(subset=['Close'])


def pct_rank(s,n=756,minimum=252):
    return s.rolling(n,min_periods=minimum).apply(lambda x:100*(np.sum(x<=x[-1])-1)/(len(x)-1),raw=True)


def option(filename,index):
    p=ROOT/filename
    if not p.exists():
        print(f'缺少 {filename}')
        return pd.Series(np.nan,index=index)
    d=pd.read_csv(p)
    if not {'date','ratio'}.issubset(d.columns): raise ValueError(f'{filename} 需要 date,ratio')
    d['date']=pd.to_datetime(d['date'],errors='coerce')
    d['ratio']=pd.to_numeric(d['ratio'],errors='coerce')
    d=d.dropna(subset=['date','ratio']).query('ratio > 0').sort_values('date').drop_duplicates('date',keep='last')
    s=d.set_index('date')['ratio']
    print(f'{filename}: {len(s)} 筆，最新 {s.index.max().date() if len(s) else "無"}')
    # At most one trading-day gap; do not silently propagate stale options values.
    return s.reindex(index).ffill(limit=1)


def margin(index):
    verified=ROOT/'margin_releases.csv'
    if verified.exists():
        d=pd.read_csv(verified)
        if not {'release_date','margin_debt'}.issubset(d.columns): raise ValueError('margin_releases.csv 欄位錯誤')
        d['release_date']=pd.to_datetime(d['release_date'],errors='coerce')
        d['margin_debt']=pd.to_numeric(d['margin_debt'],errors='coerce')
        d=d.dropna(subset=['release_date','margin_debt']).sort_values('release_date')
        if len(d)>=13:
            s=d.set_index('release_date')['margin_debt']
            print('FINRA: 使用已驗證的 release_date')
            return s.pct_change(12,fill_method=None).reindex(index,method='ffill'),'verified'
    p=ROOT/'finra_margin_monthly.csv'
    if not p.exists():
        print('FINRA 月資料缺少')
        return pd.Series(np.nan,index=index),'missing'
    d=pd.read_csv(p)
    if not {'reference_month','margin_debt'}.issubset(d.columns): raise ValueError('FINRA 月資料欄位錯誤')
    d['reference_month']=pd.to_datetime(d['reference_month'].astype(str)+'-01',errors='coerce')
    d['margin_debt']=pd.to_numeric(d['margin_debt'],errors='coerce')
    d=d.dropna(subset=['reference_month','margin_debt']).sort_values('reference_month').drop_duplicates('reference_month',keep='last')
    if len(d)<13: return pd.Series(np.nan,index=index),'missing'
    # Delay is deliberately conservative but NOT a historical publication-date archive.
    d['available_on']=d['reference_month']+pd.offsets.MonthEnd(0)+pd.Timedelta(days=45)
    d['yoy']=d['margin_debt'].pct_change(12,fill_method=None)
    s=d.set_index('available_on')['yoy'].dropna()
    print(f'FINRA: {len(d)} 個月，使用月底後45日的估計可用日（非官方公布日）')
    return s.reindex(index,method='ffill'),'estimated_45d'


def main():
    spy=market('SPY'); tw=market('^TWII'); idx=spy.index
    eq=option('equity_put_call.csv',idx); total=option('total_put_call.csv',idx)
    margin_yoy,margin_quality=margin(idx)
    walcl=fred('WALCL')/1000; tga=fred('WTREGEN')/1000
    rrp=fred('RRPONTSYD'); m2=fred('M2SL')
    liq=walcl.reindex(idx,method='ffill')-tga.reindex(idx,method='ffill')-rrp.reindex(idx,method='ffill')
    m2=m2.reindex(idx,method='ffill')
    # Difference avoids division by zero/negative liquidity denominator.
    liq_change=(liq-liq.shift(63))/liq.shift(63).abs().replace(0,np.nan)
    raw={'equity_pc':-eq.rolling(5,min_periods=3).mean(),
         'total_pc':-total.rolling(5,min_periods=3).mean(),
         'margin':margin_yoy,
         'liquidity':.7*liq_change+.3*m2.pct_change(63,fill_method=None)}
    close=spy['Close']; vol=spy['Volume']
    deviation=close/close.rolling(200).mean()-1
    momentum=close.pct_change(63,fill_method=None)
    volratio=vol/vol.rolling(60).mean()
    raw['fomo']=.45*pct_rank(deviation)+.4*pct_rank(momentum)+.15*pct_rank(volratio)
    scores=pd.DataFrame({k:(pct_rank(v) if k!='fomo' else v) for k,v in raw.items()},index=idx)
    complete=scores[list(WEIGHTS)].notna().all(axis=1)
    scores['heat']=sum(scores[k]*w for k,w in WEIGHTS.items()).where(complete)
    # Taiwan holidays are NOT US holidays; avoid forward-filling beyond 5 US trading days.
    tw_close=tw['Close'].reindex(idx).ffill(limit=5)
    drawdown=tw_close/tw_close.rolling(252,min_periods=100).max()-1
    tw_dev=tw_close/tw_close.rolling(200,min_periods=100).mean()-1
    scores['tw_close']=tw_close; scores['tw_drawdown']=drawdown
    scores['signal']=np.select([scores['heat']>=70,(scores['heat']<30)&(drawdown<=-.15)&(tw_dev<=-.08)],['散戶投機','籌碼乾淨'],default='中性')
    scores.loc[~complete,'signal']='資料不足'
    for h in (5,20,60): scores[f'tw_fwd_{h}d']=tw_close.shift(-h)/tw_close-1
    scores.to_csv(ROOT/'heat_history.csv',encoding='utf-8-sig',index_label='date')
    events=scores[scores['signal']=='籌碼乾淨']
    selected=[]; last=-999
    for dt in events.index:
        pos=idx.get_loc(dt)
        if pos-last>=20: selected.append(dt);last=pos
    cols=['heat','tw_close','tw_drawdown','tw_fwd_5d','tw_fwd_20d','tw_fwd_60d']
    scores.loc[selected,cols].to_csv(ROOT/'bottom_events.csv',encoding='utf-8-sig',index_label='date')
    (ROOT/'margin_quality.txt').write_text(margin_quality,encoding='utf-8')
    print(f'五因子完整日期數: {complete.sum()}；FINRA 日期品質: {margin_quality}')
    fig,ax=plt.subplots(figsize=(12,5))
    ax.plot(scores.index,scores['heat'],label='US speculation heat')
    ax.axhline(70,linestyle='--');ax.axhline(30,linestyle='--')
    ax.set_ylim(0,100);ax.set_ylabel('Heat 0-100')
    ax2=ax.twinx();ax2.plot(scores.index,tw_close,color='gray',alpha=.4,label='TWII')
    if selected: ax2.scatter(selected,scores.loc[selected,'tw_close'],marker='^',s=35)
    fig.tight_layout();fig.savefig(ROOT/'heat_chart.png',dpi=140);plt.close(fig)

if __name__=='__main__': main()
