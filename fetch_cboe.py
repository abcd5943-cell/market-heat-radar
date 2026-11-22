"""Cboe Equity/Total Put-Call 歷史資料增量擷取。

執行（先小批測試）：python fetch_cboe.py --start 2026-11-09 --end 2026-11-20 --limit 10
歷史補檔：python fetch_cboe.py --start 2020-01-01 --limit 30

只擷取已結束的美東日期；不覆寫既有有效資料。未能驗證的日期不寫入。
需要 requests、beautifulsoup4、pandas_market_calendars。
"""
import argparse
import csv
import os
import re
import tempfile
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas_market_calendars as mcal
import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent
URL = 'https://www.cboe.com/markets/us/options/market-statistics/daily'
FILES = {'equity': ROOT / 'equity_put_call.csv', 'total': ROOT / 'total_put_call.csv'}
KNOWN = {'2026-11-12': (0.72, 0.89), '2026-11-13': (0.63, 0.85), '2026-11-20': (0.77, 1.13)}


def load(path):
    if not path.exists():
        return {}
    with path.open(newline='', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        if not {'date', 'ratio'}.issubset(reader.fieldnames or []):
            raise ValueError(f'{path.name} 必須包含 date,ratio')
        return {row['date']: float(row['ratio']) for row in reader if row.get('date') and row.get('ratio')}


def fetch(session, day):
    for attempt in range(3):
        try:
            response = session.get(URL, params={'dt': day}, timeout=(10, 35))
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'html.parser')
            values = {}
            for tr in soup.select('tr'):
                cells = tr.find_all(['th', 'td'])
                if len(cells) < 2:
                    continue
                label = ' '.join(cells[0].stripped_strings).upper()
                if label not in ('EQUITY PUT/CALL RATIO', 'TOTAL PUT/CALL RATIO'):
                    continue
                match = re.fullmatch(r'\s*(\d+(?:\.\d+)?)\s*', cells[1].get_text(' ', strip=True))
                if match:
                    values[label] = float(match.group(1))
            if len(values) != 2:
                raise ValueError('網頁沒有完整的兩項 Put/Call Ratio')
            equity, total = values['EQUITY PUT/CALL RATIO'], values['TOTAL PUT/CALL RATIO']
            if not (0.05 <= equity <= 5 and 0.05 <= total <= 5):
                raise ValueError('比率超出合理檢查範圍')
            if day in KNOWN:
                expected = KNOWN[day]
                if abs(equity - expected[0]) > 0.011 or abs(total - expected[1]) > 0.011:
                    raise ValueError('與已驗證的基準日數值不符')
            return equity, total
        except (requests.RequestException, ValueError) as exc:
            if attempt == 2:
                raise RuntimeError(str(exc)) from exc
            time.sleep(2 * (attempt + 1))


def save_atomic(path, records):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = None
    try:
        with tempfile.NamedTemporaryFile('w', encoding='utf-8', newline='', dir=path.parent, delete=False) as f:
            tmp = Path(f.name)
            writer = csv.writer(f)
            writer.writerow(['date', 'ratio'])
            writer.writerows((d, f'{v:.4f}') for d, v in sorted(records.items()))
        os.replace(tmp, path)
    finally:
        if tmp and tmp.exists():
            tmp.unlink()


def main():
    today_et = datetime.now(ZoneInfo('America/New_York')).date()
    parser = argparse.ArgumentParser()
    parser.add_argument('--start', default='2020-01-01')
    parser.add_argument('--end', default=(today_et - timedelta(days=1)).isoformat())
    parser.add_argument('--limit', type=int, default=30, help='單次最多查詢幾個交易日，預設30')
    args = parser.parse_args()
    start, end = date.fromisoformat(args.start), date.fromisoformat(args.end)
    end = min(end, today_et - timedelta(days=1))
    if args.limit < 1 or args.limit > 150:
        parser.error('--limit 必須介於 1 到 150')
    if start > end:
        print('日期範圍沒有已結束的交易日，無需更新')
        return
    calendar = mcal.get_calendar('NYSE')
    dates = [x.strftime('%Y-%m-%d') for x in calendar.valid_days(start_date=start, end_date=end)]
    equity, total = load(FILES['equity']), load(FILES['total'])
    pending = [d for d in dates if d not in equity or d not in total][:args.limit]
    if not pending:
        print('指定範圍已補齊，無需下載')
        return
    session = requests.Session()
    session.headers.update({'User-Agent': 'Mozilla/5.0 (compatible; MarketHeatRadar/1.0)'})
    added = 0
    errors = []
    for day in pending:
        try:
            e, t = fetch(session, day)
            equity[day], total[day] = e, t
            added += 1
            print(f'{day}: Equity={e:.2f}, Total={t:.2f}', flush=True)
        except Exception as exc:
            errors.append(f'{day}: {exc}')
            print(f'未寫入 {day}: {exc}', flush=True)
        time.sleep(0.8)
    if added:
        save_atomic(FILES['equity'], equity)
        save_atomic(FILES['total'], total)
    print(f'本次成功 {added}/{len(pending)}；累積 Equity {len(equity)} 筆、Total {len(total)} 筆')
    if errors:
        print('未完成日期：' + '；'.join(errors))
    if not added:
        raise RuntimeError('本次沒有成功取得任何新資料，請檢查網站與日期')


if __name__ == '__main__':
    main()
