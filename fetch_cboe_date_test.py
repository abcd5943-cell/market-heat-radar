"""Cboe 日期診斷：只讀取公開頁面，不寫入正式 CSV。"""
import re
import sys
from datetime import datetime
import requests
from bs4 import BeautifulSoup

URL = 'https://www.cboe.com/markets/us/options/market-statistics/daily'
LABELS = {'equity': 'EQUITY PUT/CALL RATIO', 'total': 'TOTAL PUT/CALL RATIO'}
DATE_RE = re.compile(r'(?<!\d)(?:20\d{2}[-/]\d{1,2}[-/]\d{1,2}|\d{1,2}[-/]\d{1,2}[-/]20\d{2})(?!\d)')

def main():
    r = requests.get(URL, timeout=(10, 25), headers={
        'User-Agent': 'Mozilla/5.0 (compatible; PersonalMarketResearch/1.0)',
        'Accept': 'text/html,application/xhtml+xml',
    })
    r.raise_for_status()
    soup = BeautifulSoup(r.text, 'html.parser')
    ratios = {}
    for tr in soup.find_all('tr'):
        cells = [c.get_text(' ', strip=True) for c in tr.find_all(['th', 'td'])]
        if len(cells) < 2:
            continue
        label = re.sub(r'\s+', ' ', cells[0]).upper().strip()
        for key, expected in LABELS.items():
            if label == expected:
                m = re.fullmatch(r'\s*(\d+(?:\.\d+)?)\s*', cells[1].replace(',', ''))
                if m:
                    ratios[key] = float(m.group(1))
    if set(ratios) != set(LABELS):
        raise ValueError(f'比率不完整：{ratios}')
    print('=== 比率 ===')
    print('Equity Put/Call:', ratios['equity'])
    print('Total Put/Call:', ratios['total'])
    print('\n=== 頁面日期線索（尚未驗證，不代表交易日期）===')
    found = []
    for tag in soup.find_all(['input', 'time', 'meta']):
        attrs = {k: str(v)[:160] for k, v in tag.attrs.items() if k in ('type', 'name', 'id', 'value', 'datetime', 'content', 'property', 'placeholder')}
        serialized = ' '.join(attrs.values())
        if ('date' in serialized.lower() or DATE_RE.search(serialized)) and len(found) < 12:
            found.append((tag.name, attrs))
    for name, attrs in found:
        print(name, attrs)
    if not found:
        print('未在 input/time/meta 找到明確日期線索')
    # Date mentions in nearby text are clues only; avoid scripts and full-page dumping.
    for heading in soup.find_all(['h1', 'h2', 'h3']):
        label = heading.get_text(' ', strip=True)
        if 'statistic' in label.lower():
            print('頁面標題:', label[:140])
            break
    print('\n結論：日期仍須與 Cboe 日期選擇器／指定日期查詢機制核對。')
    print('安全措施：不寫入 equity_put_call.csv 或 total_put_call.csv。')

if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print(f'測試失敗：{type(exc).__name__}: {exc}', file=sys.stderr)
        sys.exit(1)
