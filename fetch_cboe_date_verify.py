"""Cboe 指定日期查詢驗證：只讀取、不寫入正式資料。"""
import re
import sys
import requests
from bs4 import BeautifulSoup

URL = 'https://www.cboe.com/markets/us/options/market-statistics/daily'
DATES = ['2026-11-12', '2026-11-13', '2026-11-20']
EXPECTED = {'2026-11-12': (0.72, 0.89)}  # Cboe 公開頁面核對基準


def get_ratios(day):
    response = requests.get(URL, params={'dt': day}, timeout=35,
                            headers={'User-Agent': 'Mozilla/5.0 (compatible; MarketHeatRadar/1.0)'})
    response.raise_for_status()
    soup = BeautifulSoup(response.text, 'html.parser')
    found = {}
    for row in soup.select('tr'):
        cells = row.find_all(['th', 'td'])
        if len(cells) < 2:
            continue
        label = ' '.join(cells[0].stripped_strings).upper()
        value = ' '.join(cells[1].stripped_strings).replace(',', '').strip()
        if label in ('EQUITY PUT/CALL RATIO', 'TOTAL PUT/CALL RATIO'):
            m = re.search(r'(?<!\d)\d+(?:\.\d+)?', value)
            if m:
                found[label] = float(m.group())
    if len(found) != 2:
        raise ValueError(f'{day}: 無法完整解析兩項比率，取得欄位：{list(found)}')
    return found['EQUITY PUT/CALL RATIO'], found['TOTAL PUT/CALL RATIO']


def main():
    results = {}
    for day in DATES:
        equity, total = get_ratios(day)
        results[day] = (equity, total)
        print(f'{day}: Equity={equity:.2f}, Total={total:.2f}', flush=True)
    base = results['2026-11-12']
    if any(abs(a - b) > 0.011 for a, b in zip(base, EXPECTED['2026-11-12'])):
        raise RuntimeError('基準日期數值與 Cboe 公開查詢結果不一致，暫停後續寫入')
    if len(set(results.values())) == 1:
        raise RuntimeError('不同日期回傳完全相同數值，疑似日期參數未生效')
    print('通過：基準日期數值吻合，且不同日期有不同結果。')
    print('提醒：這只驗證指定日期查詢；尚未開始補歷史或寫入 CSV。')


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print(f'驗證失敗：{exc}', file=sys.stderr)
        sys.exit(1)
