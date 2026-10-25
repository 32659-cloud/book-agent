# book-agent

在本機執行的 Discord agent：頻道裡有人傳書的封面照片或網路書店截圖，用 `claude -p` 辨識書名、作者、類別，記到上傳者自己的書單（Excel），並回覆在頻道。

## 規則

- 開始任何工作前，先讀 `docs/requirements.md` 和 `docs/architecture.md`。
- 四段防護要各自用清楚的註解標起來（`# ==== 防護 N：… 開始 ====` / `# ==== 防護 N 結束 ====`），一開始全部開啟：
  1. 隔離工作資料夾與限制工具
  2. 輸入當資料，不當指令（使用者的訊息文字不傳給 `claude -p`）
  3. 清洗檔名與驗證輸出
  4. 防止 Excel 公式注入
- 不可以把 `.env` commit 進 git；`DATA_DIR`（`data/`）裡的照片和 Excel 也不要 commit。
- 任何金鑰（特別是 `DISCORD_TOKEN`）不可以出現在程式、文件、commit 歷史或對話裡。
- 所有查詢和修改都用 Discord user id 篩選，只動該使用者自己的資料。
- 回覆使用繁體中文。
