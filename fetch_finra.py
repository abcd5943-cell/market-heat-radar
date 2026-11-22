#!/usr/bin/env python3
"""Download FINRA monthly margin balances; never invent historical publication dates.

Outputs:
  finra_margin_monthly.csv: reference_month,margin_debt (USD millions)
  margin_releases.csv: release_date,margin_debt (only dates independently verified)

Optional: put FINRA's official historical Excel download at finra_history.xlsx.
Install: pip install requests pandas beautifulsoup4 lxml openpyxl
"""
from __future__ import annotations
import io
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin

import pandas as pd
import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent
URL = 'https://www.finra.org/rules-guidance/key-topics/margin-accounts/margin-statistics'
MONTHLY = ROOT / 'finra_margin_monthly.csv'
RELEASES = ROOT / 'margin_releases.csv'
HEADERS = {'User-Agent': 'Mozilla/5.0 (compatible; market-heat-radar/1.0)'}


def normalize_month(value):
    s = str(value).strip()
    for fmt in ('%b-%y', '%b-%Y', '%Y-%m', '%Y-%m-%d'):
        try:
            d = datetime.strptime(s, fmt)
            return d.strftime('%Y-%m')
        except ValueError:
            pass
    d = pd.to_datetime(s, errors='coerce')
    return None if pd.isna(d) else d.strftime('%Y-%m')


def parse_tables(raw, excel=False):
    if excel:
        tables = list(pd.read_excel(io.BytesIO(raw), sheet_name=None, header=None).values())
    else:
        tables = pd.read_html(io.StringIO(raw.decode('utf-8', errors='replace')))
    records = []
    for table in tables:
        # Detect month/debit columns from header or from first several rows.
        t = table.copy()
        t.columns = [str(c).lower() for c in t.columns]
        headers = ' '.join(t.columns)
        if 'debit' not in headers:
            found = None
            for i in range(min(8, len(t))):
                vals = [str(x).strip().lower() for x in t.iloc[i].tolist()]
                if any('debit' in x for x in vals):
                    found = i
                    break
            if found is None:
                continue
            t.columns = [str(x).lower() for x in t.iloc[found].tolist()]
            t = t.iloc[found+1:]
        debit_cols = [c for c in t.columns if 'debit' in c]
        if not debit_cols:
            continue
        debit = debit_cols[0]
        date_cols = [c for c in t.columns if any(k in c for k in ('month', 'date', 'year'))]
        date_col = date_cols[0] if date_cols else t.columns[0]
        for _, row in t.iterrows():
            month = normalize_month(row[date_col])
            number = pd.to_numeric(re.sub(r'[^0-9.\-]', '', str(row[debit])), errors='coerce')
            if month and pd.notna(number) and number > 1000:
                records.append((month, float(number)))
    return records


def merge_monthly(records):
    old = []
    if MONTHLY.exists():
        d = pd.read_csv(MONTHLY)
        if {'reference_month','margin_debt'}.issubset(d.columns):
            old = list(d[['reference_month','margin_debt']].itertuples(index=False, name=None))
    combined = {}
    for month, amount in old + records:
        month = normalize_month(month)
        if month and pd.notna(amount):
            combined[month] = float(amount)
    if not combined:
        raise RuntimeError('FINRA 未取得任何有效融資資料')
    df = pd.DataFrame([{'reference_month': m, 'margin_debt': v} for m,v in sorted(combined.items())])
    df.to_csv(MONTHLY, index=False)
    return df


def main():
    r = requests.get(URL, headers=HEADERS, timeout=(15, 45))
    r.raise_for_status()
    records = parse_tables(r.content)
    print('FINRA 網頁解析:', len(records), '筆')
    # Official history may require downloading Excel via a dynamically generated button.
    local_excel = ROOT / 'finra_history.xlsx'
    if local_excel.exists():
        try:
            more = parse_tables(local_excel.read_bytes(), excel=True)
            records.extend(more)
            print('官方 Excel 歷史資料:', len(more), '筆')
        except Exception as exc:
            raise RuntimeError(f'無法解析 finra_history.xlsx: {exc}') from exc
    else:
        soup = BeautifulSoup(r.text, 'html.parser')
        candidates = []
        for a in soup.select('a[href]'):
            href = a.get('href', '')
            label = a.get_text(' ', strip=True).lower()
            if ('.xlsx' in href.lower() or '.xls' in href.lower()) and ('margin' in href.lower() or 'data' in label):
                candidates.append(urljoin(URL, href))
        for url in dict.fromkeys(candidates):
            try:
                x = requests.get(url, headers=HEADERS, timeout=(15,45))
                x.raise_for_status()
                if x.content[:2] == b'PK' or x.content[:4] == bytes.fromhex('D0CF11E0'):
                    more = parse_tables(x.content, excel=True)
                    if len(more) >= 24:
                        records.extend(more)
                        print('官方 Excel 歷史資料:', len(more), '筆')
                        break
            except Exception as exc:
                print('Excel 連結無法讀取:', str(exc)[:160])
    df = merge_monthly(records)
    print('歷史月份:', len(df), '範圍:', df.iloc[0]['reference_month'], '至', df.iloc[-1]['reference_month'])
    # Do not map reference-month to a guessed release date. Existing verified release data is preserved.
    if RELEASES.exists():
        existing = pd.read_csv(RELEASES)
        if not {'release_date', 'margin_debt'}.issubset(existing.columns):
            raise RuntimeError('margin_releases.csv 欄位必須為 release_date,margin_debt')
        print('保留已驗證公布日期:', len(existing), '筆')
    else:
        print('尚未建立 margin_releases.csv：FINRA 月份不等於實際公布日期。')
        print('請提供可查證的歷史公布日，或另行建立逐月首次觀測紀錄，才能做無前視偏誤回測。')
    if len(df) < 24:
        print('注意：歷史月份不足 24 筆。請從 FINRA 官網下載歷史 Excel，命名 finra_history.xlsx 後重新執行。')


if __name__ == '__main__':
    main()
