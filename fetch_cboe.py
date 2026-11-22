"""Cboe Equity / Total Put-Call 歷史回補與每日增量更新。

首次回補（建議每次 30 筆）：
    python fetch_cboe.py --start 2020-01-01 --limit 30
只補最近一段期間：
    python fetch_cboe.py --start 2026-11-01 --limit 30
指定區間／由舊到新：
    python fetch_cboe.py --start 2022-01-01 --end 2022-12-31 --limit 30 --order oldest

輸出 equity_put_call.csv、total_put_call.csv；重跑不覆寫已有日期。
注意：必須將 CSV commit 回 GitHub，否則下一次 Actions 會從空白狀態重來。
依賴：requests beautifulsoup4 pandas_market_calendars
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
EQUITY_FILE = ROOT / 'equity_put_call.csv'
TOTAL_FILE = ROOT / 'total_put_call.csv'
KNOWN = {'2026-11-12': (0.72, 0.89), '2026-11-13': (0.63, 0.85), '2026-11-20': (0.77, 1.13)}
LABELS = {'EQUITY PUT/CALL RATIO': 'equity', 'TOTAL PUT/CALL RATIO': 'total'}


def read_csv(path):
    if not path.exists():
        return {}
    result = {}
    with path.open(newline='', encoding='utf-8-sig') as stream:
        reader = csv.DictReader(stream)
        if not {'date', 'ratio'}.issubset(reader.fieldnames or []):
            raise ValueError(f'{path.name} 欄位必須是 date,ratio')
        for row in reader:
            day, value = row.get('date', '').strip(), row.get('ratio', '').strip()
            if not day or not value:
                continue
            date.fromisoformat(day)
            number = float(value)
            if not 0.05 <= number <= 5:
                raise ValueError(f'{path.name} {day} 比率超出檢查範圍')
            if day in result and result[day] != number:
                raise ValueError(f'{path.name} {day} 出現衝突的重複日期')
            result[day] = number
    return result


def get_ratios(session, day):
    for attempt in range(3):
        try:
            response = session.get(URL, params={'dt': day}, timeout=(10, 35))
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'html.parser')
            found = {}
            for tr in soup.select('tr'):
                cells = tr.find_all(['th', 'td'])
                if len(cells) < 2:
                    continue
                label = ' '.join(cells[0].stripped_strings).upper()
                if label not in LABELS:
                    continue
                match = re.fullmatch(r'\s*(\d+(?:\.\d+)?)\s*', cells[1].get_text(' ', strip=True))
                if match:
                    found[LABELS[label]] = float(match.group(1))
            if set(found) != {'equity', 'total'}:
                raise ValueError('未找到完整 Equity / Total Put/Call Ratio')
            equity, total = found['equity'], found['total']
            if not (0.05 <= equity <= 5 and 0.05 <= total <= 5):
                raise ValueError('比率超出檢查範圍')
            if day in KNOWN and (abs(equity - KNOWN[day][0]) > 0.011 or abs(total - KNOWN[day][1]) > 0.011):
                raise ValueError('基準日數值不符，可能忽略了指定日期')
            return equity, total
        except (requests.RequestException, ValueError) as exc:
            if attempt == 2:
                raise RuntimeError(str(exc)) from exc
            time.sleep(2 * (attempt + 1))


def write_csv(path, rows):
    temp = None
    try:
        with tempfile.NamedTemporaryFile('w', newline='', encoding='utf-8', dir=path.parent, delete=False) as stream:
            temp = Path(stream.name)
            writer = csv.writer(stream)
            writer.writerow(['date', 'ratio'])
            writer.writerows((day, f'{value:.4f}') for day, value in sorted(rows.items()))
        os.replace(temp, path)
    finally:
        if temp is not None and temp.exists():
            temp.unlink()


def main():
    parser = argparse.ArgumentParser(description='增量回補 Cboe Put/Call 歷史資料')
    parser.add_argument('--start', default='2020-01-01', help='最早日期 YYYY-MM-DD')
    parser.add_argument('--end', help='最晚日期 YYYY-MM-DD；預設美東昨天')
    parser.add_argument('--limit', type=int, default=30, help='每次最多查詢幾個日期，1～100')
    parser.add_argument('--order', choices=['newest', 'oldest'], default='newest', help='預設先補最近的資料')
    parser.add_argument('--delay', type=float, default=1.0, help='每次查詢間隔秒數，至少 0.5')
    args = parser.parse_args()
    if not 1 <= args.limit <= 100:
        parser.error('--limit 必須介於 1～100')
    if args.delay < 0.5:
        parser.error('--delay 不得小於 0.5 秒')
    today_et = datetime.now(ZoneInfo('America/New_York')).date()
    start = date.fromisoformat(args.start)
    end = min(date.fromisoformat(args.end) if args.end else today_et - timedelta(days=1), today_et - timedelta(days=1))
    if start > end:
        print('沒有需要更新的日期')
        return

    equity, total = read_csv(EQUITY_FILE), read_csv(TOTAL_FILE)
    calendar = mcal.get_calendar('NYSE')
    days = [d.strftime('%Y-%m-%d') for d in calendar.valid_days(start_date=start, end_date=end)]
    if args.order == 'newest':
        days.reverse()
    pending = [day for day in days if day not in equity or day not in total][:args.limit]
    if not pending:
        print(f'無待補日期。Equity={len(equity)} 筆，Total={len(total)} 筆')
        return

    session = requests.Session()
    session.headers.update({'User-Agent': 'Mozilla/5.0 (compatible; MarketHeatRadar/1.0)'})
    success, failed = 0, []
    try:
        for day in pending:
            try:
                e, t = get_ratios(session, day)
                equity[day], total[day] = e, t
                success += 1
                print(f'{day}: Equity={e:.2f}, Total={t:.2f}', flush=True)
            except Exception as exc:
                failed.append(day)
                print(f'{day}: 下載失敗：{exc}', flush=True)
            # 每筆成功即儲存；GitHub Actions 中斷時，已取得資料仍在工作目錄
            if success:
                write_csv(EQUITY_FILE, equity)
                write_csv(TOTAL_FILE, total)
            time.sleep(args.delay)
    finally:
        session.close()

    print(f'本次成功 {success}/{len(pending)}；累積 Equity={len(equity)}、Total={len(total)} 筆')
    if failed:
        print('失敗日期：' + ', '.join(failed))
    if not success:
        raise RuntimeError('本次未成功取得任何新資料')
    if failed:
        print('部分日期未成功，之後重跑會再嘗試；不得將缺漏資料視為完整。')


if __name__ == '__main__':
    main()
