"""Cboe Put/Call 歷史資料小批次下載（先測試，不寫入正式 CSV）。
執行：python fetch_cboe_history.py
"""
import csv
import re
import time
from datetime import date, timedelta
from pathlib import Path
import requests
from bs4 import BeautifulSoup

URL = 'https://www.cboe.com/markets/us/options/market-statistics/daily'
ROOT = Path(__file__).resolve().parent
OUT = ROOT / 'cboe_history_test.csv'
START = date(2026, 11, 9)
END = date(2026, 11, 20)
KNOWN = {date(2026, 11, 12): (0.72, 0.89), date(2026, 11, 13): (0.63, 0.85), date(2026, 11, 20): (0.77, 1.13)}


def fetch(session, day):
    r = session.get(URL, params={'dt': day.isoformat()}, timeout=35)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, 'html.parser')
    values = {}
    for tr in soup.select('tr'):
        cells = tr.find_all(['th', 'td'])
        if len(cells) < 2:
            continue
        label = ' '.join(cells[0].stripped_strings).upper()
        if label not in ('EQUITY PUT/CALL RATIO', 'TOTAL PUT/CALL RATIO'):
            continue
        match = re.search(r'(?<!\d)\d+(?:\.\d+)?', ' '.join(cells[1].stripped_strings).replace(',', ''))
        if match:
            values[label] = float(match.group())
    if len(values) != 2:
        raise ValueError(f'{day}: 找不到兩個比率')
    return values['EQUITY PUT/CALL RATIO'], values['TOTAL PUT/CALL RATIO']


def main():
    session = requests.Session()
    session.headers.update({'User-Agent': 'Mozilla/5.0 (compatible; MarketHeatRadar/1.0)'})
    rows = []
    day = START
    while day <= END:
        if day.weekday() < 5:
            try:
                equity, total = fetch(session, day)
                if day in KNOWN and (abs(equity - KNOWN[day][0]) > .011 or abs(total - KNOWN[day][1]) > .011):
                    raise ValueError(f'{day}: 與已核對基準不符')
                rows.append((day.isoformat(), equity, total))
                print(f'{day}: Equity={equity:.2f}, Total={total:.2f}', flush=True)
            except Exception as e:
                print(f'跳過 {day}: {e}', flush=True)
            time.sleep(0.8)
        day += timedelta(days=1)
    if not all(d.isoformat() in {row[0] for row in rows} for d in KNOWN):
        raise RuntimeError('基準日期缺漏：不輸出測試檔')
    # 僅為診斷檔；不能假設所有平日都有交易，正式匯入前仍須核對交易日與假日。
    with OUT.open('w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow(['date', 'equity_ratio', 'total_ratio'])
        w.writerows(rows)
    print(f'測試完成：{len(rows)} 筆，輸出 {OUT.name}（非正式資料）')


if __name__ == '__main__':
    main()
