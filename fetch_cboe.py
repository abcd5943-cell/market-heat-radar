"""Cboe Equity / Total Put-Call 歷史回補；遇到限流立即停止。

使用：python fetch_cboe.py --start 2020-01-01 --limit 25 --order newest --delay 10
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


class RateLimited(Exception):
    """伺服器拒絕或限制請求：停止整批，不重試。"""


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
    # 只重試暫時性網路錯誤與 5xx；403/429 一律立即停止
    for attempt in range(2):
        try:
            response = session.get(URL, params={'dt': day}, timeout=(10, 35))
            if response.status_code in (403, 429):
                raise RateLimited(f'HTTP {response.status_code}：Cboe 已拒絕／限制請求，立即停止本批次')
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
                raise ValueError('頁面缺少完整 Equity / Total Put/Call Ratio（不重試，以免重複請求）')
            equity, total = found['equity'], found['total']
            if not (0.05 <= equity <= 5 and 0.05 <= total <= 5):
                raise ValueError('比率超出合理範圍')
            if day in KNOWN and (abs(equity - KNOWN[day][0]) > .011 or abs(total - KNOWN[day][1]) > .011):
                raise ValueError('基準日期數值不符，可能忽略指定日期')
            return equity, total
        except RateLimited:
            raise
        except requests.HTTPError as exc:
            status = exc.response.status_code if exc.response is not None else None
            if status is None or status < 500 or attempt == 1:
                raise
        except (requests.Timeout, requests.ConnectionError):
            if attempt == 1:
                raise
        if attempt == 0:
            time.sleep(30)


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
    parser = argparse.ArgumentParser(description='保守型 Cboe 增量歷史回補')
    parser.add_argument('--start', default='2020-01-01')
    parser.add_argument('--end')
    parser.add_argument('--limit', type=int, default=25)
    parser.add_argument('--order', choices=['newest', 'oldest'], default='newest')
    parser.add_argument('--delay', type=float, default=10.0)
    args = parser.parse_args()
    if not 1 <= args.limit <= 25:
        parser.error('--limit 必須介於 1～25')
    if args.delay < 10:
        parser.error('--delay 至少 10 秒')

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
    session.headers.update({'User-Agent': 'MarketHeatRadar/1.0 (historical research)'})
    success, failed, blocked = 0, [], False
    try:
        for i, day in enumerate(pending):
            if i:
                time.sleep(args.delay)
            try:
                e, t = get_ratios(session, day)
                equity[day], total[day] = e, t
                write_csv(EQUITY_FILE, equity)
                write_csv(TOTAL_FILE, total)
                success += 1
                print(f'{day}: Equity={e:.2f}, Total={t:.2f}', flush=True)
            except RateLimited as exc:
                print(f'{day}: {exc}；停止所有後續查詢，請暫停排程並檢查', flush=True)
                blocked = True
                break
            except (requests.RequestException, ValueError) as exc:
                failed.append(day)
                print(f'{day}: 跳過（{type(exc).__name__}: {exc}）', flush=True)
    finally:
        session.close()

    print(f'本次成功 {success}/{len(pending)}；累積 Equity={len(equity)}、Total={len(total)} 筆')
    if failed:
        print('未取得日期：' + ', '.join(failed))
    if blocked:
        raise RateLimited('偵測到 403/429，已停止回補；已取得的 CSV 保留供工作流程提交')
    if not success and pending:
        raise RuntimeError('本批沒有取得新資料，請檢查來源或休市日期')


if __name__ == '__main__':
    main()
