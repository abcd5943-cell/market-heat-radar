"""美股投機熱度 / 台股抄底訊號研究工具。需要 FRED_API_KEY 環境變數。"""
from pathlib import Path
import os
import time
import numpy as np
import pandas as pd
import requests
import yfinance as yf
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parent
START = '2015-01-01'
WEIGHTS = {'equity_pc': .25, 'total_pc': .15, 'margin': .15, 'liquidity': .20, 'fomo': .25}

def fred(series):
    key = os.environ.get('FRED_API_KEY', '').strip()
    if not key:
        raise RuntimeError('缺少 FRED_API_KEY：請在 GitHub Repository secrets 設定金鑰，並由 workflow 傳入')
    url = 'https://api.stlouisfed.org/fred/series/observations'
    params = {'series_id': series, 'api_key': key, 'file_type': 'json', 'observation_start': START}
    for attempt in range(3):
        try:
            r = requests.get(url, params=params, timeout=(10, 25), headers={'User-Agent': 'market-heat-radar/1.0'})
            r.raise_for_status()
            data = r.json()
            observations = data.get('observations', [])
            if not observations:
                raise RuntimeError(f'FRED {series} 回傳空資料')
            df = pd.DataFrame(observations)
            s = pd.Series(pd.to_numeric(df['value'], errors='coerce').to_numpy(), index=pd.to_datetime(df['date']), name=series)
            s = s.sort_index().dropna()
            if s.empty:
                raise RuntimeError(f'FRED {series} 沒有有效數值')
            print(f'FRED {series}: {len(s)} 筆，最新觀測日期 {s.index[-1].date()}', flush=True)
            return s
        except requests.HTTPError as exc:
            if exc.response is not None and exc.response.status_code in (400, 401, 403):
                raise RuntimeError(f'FRED {series} API 認證或參數錯誤 (HTTP {exc.response.status_code})，請檢查 API Key') from exc
            error = exc
        except (requests.RequestException, ValueError) as exc:
            error = exc
        if attempt < 2:
            time.sleep(3 * (attempt + 1))
    raise RuntimeError(f'FRED {series} API 下載失敗（重試 3 次）: {type(error).__name__}') from error

def market(symbol):
    d = yf.download(symbol, start=START, auto_adjust=True, progress=False)
    if d.empty: raise RuntimeError(f'無法取得 {symbol} 行情')
    if isinstance(d.columns, pd.MultiIndex): d.columns = d.columns.get_level_values(0)
    return d[['Close','Volume']].dropna()

def pct_rank(s, n=756, minimum=252):
    return s.rolling(n, min_periods=minimum).apply(lambda x: 100 * (np.sum(x <= x[-1]) - 1) / (len(x)-1), raw=True)

def csv_option(filename, index):
    p = ROOT / filename
    if not p.exists(): return pd.Series(index=index, dtype=float)
    d = pd.read_csv(p)
    if not {'date','ratio'}.issubset(d.columns): raise ValueError(f'{filename} 需要 date,ratio 欄位')
    s = pd.Series(pd.to_numeric(d['ratio'],errors='coerce').values, index=pd.to_datetime(d['date']))
    return s.sort_index().groupby(level=0).last().reindex(index).ffill(limit=5)

def main():
    spy = market('SPY'); tw = market('^TWII')
    idx = spy.index
    raw = {}
    raw['equity_pc'] = -csv_option('equity_put_call.csv', idx).rolling(5,min_periods=3).mean()
    raw['total_pc'] = -csv_option('total_put_call.csv', idx).rolling(5,min_periods=3).mean()
    p = ROOT/'margin_releases.csv'
    if p.exists():
        m = pd.read_csv(p)
        if not {'release_date','margin_debt'}.issubset(m): raise ValueError('margin_releases.csv 需要 release_date,margin_debt')
        m = m.assign(release_date=pd.to_datetime(m.release_date)).sort_values('release_date').set_index('release_date')['margin_debt'].astype(float)
        # 月增資料的 12 期年增率，依實際公布日才提供給模型
        raw['margin'] = m.pct_change(12).reindex(idx, method='ffill')
    else:
        raw['margin'] = pd.Series(index=idx,dtype=float)
    walcl = fred('WALCL')/1000
    tga = fred('WTREGEN')/1000
    rrp = fred('RRPONTSYD')
    m2 = fred('M2SL')
    # 先按交易日對齊不同頻率，再做淨流動性計算
    liquidity = walcl.reindex(idx, method='ffill') - tga.reindex(idx, method='ffill') - rrp.reindex(idx, method='ffill')
    m2 = m2.reindex(idx, method='ffill')
    raw['liquidity'] = .7*liquidity.pct_change(63, fill_method=None)+.3*m2.pct_change(63, fill_method=None)
    close=spy.Close; volume=spy.Volume
    deviation=close/close.rolling(200).mean()-1
    momentum=close.pct_change(63)
    volratio=volume/volume.rolling(60).mean()
    raw['fomo']=.45*pct_rank(deviation)+.4*pct_rank(momentum)+.15*pct_rank(volratio)
    scores=pd.DataFrame({k: (pct_rank(v) if k!='fomo' else v) for k,v in raw.items()})
    complete=scores[list(WEIGHTS)].notna().all(axis=1)
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
    plt.close(fig)
    print('\n輸出：heat_history.csv, bottom_events.csv, heat_chart.png')

if __name__=='__main__': main()
