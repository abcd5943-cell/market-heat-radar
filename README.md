# 市場熱度雷達 — iPhone 網頁版

## 目前狀態
網站介面、五因子演算法、台股抄底訊號、回測統計與每日 GitHub Actions 排程已提供。**尚未完成 Cboe/FINRA 的免人工資料擷取**；這兩項來源必須提供真實 CSV，否則網頁明確顯示資料不足，絕不造假分數。初次開啟時沒有真實歷史資料是正常現象。

## 如何部署（免費）
1. 註冊／登入 GitHub，建立新的公開 repository（例如 market-heat-radar）。
2. 將此 ZIP 解壓縮後的**內容**上傳到 repository 根目錄，包含 `.github/workflows/update.yml` 隱藏資料夾。
3. Repository → Settings → Pages → Build and deployment → Deploy from a branch → main / (root) → Save。
4. 等待 GitHub Pages 建立網址，通常為 `https://你的帳號.github.io/market-heat-radar/`。
5. Repository → Actions → 每日更新市場熱度 → Run workflow，首次手動執行一次。之後週一至週五 23:20 UTC 嘗試更新（台灣時間週二至週六 07:20），GitHub 排程可能延遲或偶爾漏跑。
6. iPhone Safari 開啟 GitHub Pages 網址 → 分享 → 加入主畫面。

## 真實資料（必填）
請將以下檔案放在 repository 根目錄（與 market_heat.py 同層）：
- `equity_put_call.csv`：`date,ratio`，每日 Cboe Equity Put/Call
- `total_put_call.csv`：`date,ratio`，每日 Cboe Total Put/Call
- `margin_releases.csv`：`release_date,margin_debt`，FINRA 月度融資餘額；**日期須為實際公布日**，不可用統計月底冒充。

參考來源：
- https://www.cboe.com/us/options/market_statistics/historical_data/
- https://www.finra.org/rules-guidance/key-topics/margin-accounts/margin-statistics
- https://fred.stlouisfed.org/

此版本的 GitHub Action 不會自行下載或更新上述三個 CSV。要做到真正全自動五因子，需要額外開發並驗證來源擷取器，或使用可靠的付費數據 API；否則即使排程成功，也不代表完整分數是最新的。

## 重要限制
- 回測使用 FRED 當前歷史版本，可能包含事後修訂。嚴格回測應採 ALFRED 歷史版本並對齊實際公布時間。
- 台股與美股休市日期不同，目前以美股交易日為基準；同日台股收盤時序可能早於美股訊號，不能把同日訊號視為台股盤中已知資訊。
- 低於 30 不等於台股已落底，需同時符合跌幅與均線條件。
- 本工具為研究用途，非投資建議。網站不提供券商交易功能。
