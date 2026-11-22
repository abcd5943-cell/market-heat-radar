"""Cboe 官方每日 Put/Call 比率連線測試（不覆寫正式資料）。
執行：python fetch_cboe.py
需要：requests, pandas, beautifulsoup4
"""
import re
import sys
import requests
from bs4 import BeautifulSoup

URL = 'https://www.cboe.com/markets/us/options/market-statistics/daily'
LABELS = {'equity': 'EQUITY PUT/CALL RATIO', 'total': 'TOTAL PUT/CALL RATIO'}


def get_ratios():
    response = requests.get(URL, timeout=(10, 25), headers={
        'User-Agent': 'Mozilla/5.0 (compatible; PersonalMarketResearch/1.0)',
        'Accept': 'text/html,application/xhtml+xml',
    })
    response.raise_for_status()
    soup = BeautifulSoup(response.text, 'html.parser')
    ratios = {}
    # Parse only table rows, not arbitrary page text or unrelated numbers.
    for tr in soup.find_all('tr'):
        cells = [c.get_text(' ', strip=True) for c in tr.find_all(['th', 'td'])]
        if len(cells) < 2:
            continue
        label = re.sub(r'\s+', ' ', cells[0]).upper().strip()
        for key, expected in LABELS.items():
            if label == expected:
                match = re.fullmatch(r'\s*(\d+(?:\.\d+)?)\s*', cells[1].replace(',', ''))
                if match:
                    value = float(match.group(1))
                    if 0 <= value <= 100:
                        ratios[key] = value
    if set(ratios) != set(LABELS):
        raise ValueError(f'找不到完整 Cboe 比率，已找到：{list(ratios)}。網站可能使用動態載入或變更版型。')
    return ratios


if __name__ == '__main__':
    try:
        result = get_ratios()
        print('Cboe 網頁解析成功（尚未驗證交易日期，不寫入正式 CSV）')
        print(f"Equity Put/Call: {result['equity']}")
        print(f"Total Put/Call:  {result['total']}")
        print('下一步需驗證交易日期、歷史資料取得方式及授權條件。')
    except Exception as exc:
        print(f'Cboe 測試失敗：{type(exc).__name__}: {exc}', file=sys.stderr)
        sys.exit(1)
