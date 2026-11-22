"""美股投機熱度 / 台股抄底訊號研究工具。 pip install pandas numpy yfinance requests matplotlib"""
from pathlib import Path
import io
import numpy as np
import pandas as pd
import requests
import yfinance as yf
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parent
START = '2015-01-01'
WEIGHTS = {'equity_pc': .25, 'total_pc': .15, 'margin': .15, 'liquidity': .20, 'fomo': .25}

def fred(series):
    url = f'https://fred.stlouisfed.org/graph/fredgraph.csv?id={series}'
    r = requests.get(url, timeout=30, headers={'User-Agent':'Mozilla/5.0'}); r.raise_for_status()
    df = pd.read_csv(io.StringIO(r.text))
    df.columns = ['date', series]
    df['date'] = pd.to_datetime(df['date'])
    return df.set_index('date')[series].pipe(pd.to_numeric, errors='coerce')

def market(symbol):
    d = yf.download(symbol, start=START, auto_adjust=True, progress=False)
    if d.empty: raise RuntimeError(f'無法取得 {symbol} 行情')
    if isinstance(d.columns, pd.MultiIndex): d.columns = d.columns.get_level_values(0)
    return d[['Close','Volume']].dropna()

def pct_rank(s, n=756, minimum=252):
    return s.rolling(n, min_periods=minimum).apply(lambda x: 100 * (np.sum(x <= x[-1]) - 1) / (len(x)-1), raw=True)

def csv_option(filename, index):
    p=ROOT / filename
    if not p.exists(): return pd.Series(index=index, dtype=float)
    d=pd.read_csv(p)
    if not {'date','ratio'}.issubset(d.columns): raise ValueError(f'{filename} 需要 date,ratio 欄位')
    s=pd.Series(pd.to_numeric(d['ratio'],errors='coerce').values, index=pd.to_datetime(d['date']))
    return s.sort_index().groupby(level=0).last().reindex(index).ffill(limit=5)

def main():
    spy=market('SPY'); tw=market('^TWII')
    idx=spy.index
    raw={}
    raw['equity_pc']=-csv_option('equity_put_call.csv',idx).rolling(5,min_periods=3).mean()
    raw['total_pc']=-csv_option('total_put_call.csv',idx).rolling(5,min_periods=3).mean()
    # FINRA 月資料需手動填入公布日，避免使用事後才知道的資料
    p=ROOT/'margin_releases.csv'
    if p.exists():
        m=pd.read_csv(p)
        if not {'release_date','margin_debt'}.issubset(m): raise ValueError('margin_releases.csv 需要 release_date,margin_debt')
        m=m.assign(release_date=pd.to_datetime(m.release_date)).sort_values('release_date').set_index('release_date')['margin_debt'].astype(float)
        raw['margin']=m.pct_change(12).reindex(idx).ffill()
    else: raw['margin']=pd.Series(index=idx,dtype=float)
    # FRED 不同單位：WALCL/WTREGEN 百萬美元，RRPONTSYD/M2SL 十億美元
    walcl=fred('WALCL')/1000; tga=fred('WTREGEN')/1000
    rrp=fred('RRPONTSYD'); m2=fred('M2SL')
    liquidity=(walcl-tga-rrp).reindex(idx).ffill()
    m2=m2.reindex(idx).ffill()
    raw['liquidity']=.7*liquidity.pct_change(63)+.3*m2.pct_change(63)
    close=spy.Close; volume=spy.Volume
    deviation=close/close.rolling(200).mean()-1
    momentum=close.pct_change(63)
    volratio=volume/volume.rolling(60).mean()
    raw['fomo']=.45*pct_rank(deviation)+.4*pct_rank(momentum)+.15*pct_rank(volratio)
    scores=pd.DataFrame({k: (pct_rank(v) if k!='fomo' else v) for k,v in raw.items()})
    # 缺少任一成分，不偽裝成完整的五因子指標
    complete=scores.notna().all(axis=1)
    scores['heat']=sum(scores[k]*w for k,w in WEIGHTS.items()).where(complete)
    tw_close=tw.Close.reindex(idx).ffill(limit=5)
    tw_drawdown=tw_close/tw_close.rolling(252,min_periods=100).max()-1
    tw_deviation=tw_close/tw_close.rolling(200,min_periods=100).mean()-1
    scores['tw_close']=tw_close
    scores['tw_drawdown']=tw_drawdown
    scores['signal']=np.select([scores.heat>=70,(scores.heat<30)&(tw_drawdown<=-.15)&(tw_deviation<=-.08)],['散戶投機','籌碼乾淨'],default='中性')
    scores.loc[~complete,'signal']='資料不足'
    for h in (5,20,60): scores[f'tw_fwd_{h}d']=tw_close.shift(-h)/tw_close-1
    scores.to_csv(ROOT/'heat_history.csv',encoding='utf-8-sig',index_label='date')
    signals=scores[scores.signal=='籌碼乾淨'].copy()
    # 連續訊號僅保留第一天，且 20 交易日內不重複進場
    selected=[]; last=-999
    for date in signals.index:
        pos=idx.get_loc(date)
        if pos-last>=20: selected.append(date);last=pos
    events=scores.loc[selected,['heat','tw_close','tw_drawdown','tw_fwd_5d','tw_fwd_20d','tw_fwd_60d']]
    events.to_csv(ROOT/'bottom_events.csv',encoding='utf-8-sig',index_label='date')
    print('最新完整五因子資料：')
    print(scores.loc[complete,['heat','signal']].tail(1).to_string() if complete.any() else '缺少必要資料，無法計算；請補上三份 CSV')
    print('\n回測（獨立訊號；尚未計入交易成本）：')
    for h in (5,20,60):
        x=events[f'tw_fwd_{h}d'].dropna()
        print(f'{h}日: 樣本={len(x)}, 勝率={x.gt(0).mean():.1%}, 平均報酬={x.mean():.2%}' if len(x) else f'{h}日: 無樣本')
    fig,ax=plt.subplots(figsize=(13,6))
    ax.plot(scores.index,scores.heat,label='US speculation heat')
    ax.axhline(70,linestyle='--');ax.axhline(30,linestyle='--')
    ax.set_ylim(0,100);ax.set_ylabel('Heat score (0-100)')
    ax2=ax.twinx();ax2.plot(scores.index,tw_close,alpha=.35,label='TWII',color='gray')
    ax2.scatter(events.index,events.tw_close,marker='^',s=35,label='Bottom signals')
    ax2.set_ylabel('TWII');fig.tight_layout();fig.savefig(ROOT/'heat_chart.png',dpi=160)
    print('\n輸出：heat_history.csv, bottom_events.csv, heat_chart.png')

if __name__=='__main__': main()
