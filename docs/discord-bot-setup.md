# Discord bot 設定

這份帶你在 Discord Developer Portal 建立一個 bot、拿到 token、把 bot 邀進你的 Server。

> Discord 的畫面偶爾會改版，按鈕位置可能略有不同，名稱通常一樣。以下以 Windows 瀏覽器為準。

## ⚠️ 先看這個：bot token 的規則

**bot token 等於 bot 的密碼。拿到 token 的人，可以完全控制你的 bot。**

- **絕對不能**貼給任何人
- **絕對不能**貼進 Claude Code 的對話（包括這個對話）
- **絕對不能** commit 進 git，也不能出現在任何文件裡
- 只能放在你電腦上的 `.env` 檔案裡（`.env` 已經被 `.gitignore` 擋住，不會上傳）

萬一不小心外洩：馬上回到下面的第 3 步按「Reset Token」重設，舊的 token 立刻失效。如果 token 已經被 commit 進 GitHub，除了重設，作業規定還要**重新開一個新的 repo**。

## 1. 建立 application

1. 用瀏覽器打開 https://discord.com/developers/applications ，登入你的 Discord 帳號。
2. 右上角按「**New Application**」。
3. 名稱輸入 `book-agent`（或你喜歡的名字），勾選同意條款，按「Create」。

## 2. 建立 bot 並打開必要的設定

1. 在左邊選單點「**Bot**」。（新帳號的 application 通常已經自動有一個 bot。）
2. 往下找到「**Privileged Gateway Intents**」。
3. 打開「**Message Content Intent**」，然後按下面的「Save Changes」。

**為什麼一定要打開 Message Content Intent？**
Discord 預設不讓 bot 讀訊息的文字內容，只看得到「有訊息」。我們的 agent 要讀 `!書單`、`!已讀 3` 這類指令，也要看訊息有沒有「想買」，所以必須打開。沒打開的話，bot 會連線成功，但完全讀不到指令。

## 3. 拿到 bot token

1. 還在「Bot」頁，找到「**Token**」那一區。
2. 按「**Reset Token**」，確認後會顯示一串很長的字。
3. 按「**Copy**」複製。（這串字**只會顯示一次**，離開頁面就看不到了，要再看只能重設。）
4. 先不要貼到任何地方，直接做下面第 5 步，把它貼進 `.env`。

## 4. 把 bot 邀進你的 Server

1. 左邊選單點「**OAuth2**」。
2. 往下找到「**OAuth2 URL Generator**」。
3. 「Scopes」勾選：**bot**。
4. 勾了 bot 之後，下面會出現「Bot Permissions」，勾選這些：
   - **View Channels**（檢視頻道）
   - **Send Messages**（傳送訊息）
   - **Read Message History**（讀取訊息歷史記錄）
   - **Pin Messages**（釘選訊息，用來置頂使用說明；比「管理訊息」小，不能刪別人的訊息）

   中文介面的對照：檢視頻道在「一般權限」，其餘三項在「文字權限」。其他都不勾。
5. 最下面會產生一串「Generated URL」，按「Copy」。
6. 在瀏覽器網址列貼上這個網址，Enter。
7. 「新增至伺服器」選你的 Server，按「繼續」，再按「授權」，完成驗證。
8. 回到 Discord，你的 Server 成員列表應該出現這個 bot（顯示為離線，正常，因為程式還沒跑）。

只勾這幾項是刻意的：權限越少，萬一出事影響越小。

## 5. 建立 `.env`

在專案資料夾 `C:\Users\penny\book-agent` 裡建立一個叫 `.env` 的檔案（檔名開頭有一個點，沒有其他副檔名）。內容如下，**值要自己填**：

```
DISCORD_TOKEN=貼上你剛剛複製的token
CHANNEL_ID=貼上你暫存的頻道ID
CLAUDE_MODEL=haiku
DATA_DIR=./data
```

建立方式（擇一）：
- 用 VS Code：在專案資料夾新增檔案，取名 `.env`，貼上內容並存檔。
- 用記事本：另存新檔，檔名輸入 `".env"`（連雙引號一起打，避免變成 `.env.txt`），存檔類型選「所有檔案」。

**token 只貼在這個檔案，不要貼到其他任何地方。**

## 6. 做完請確認

- [ ] Message Content Intent 已打開並按了 Save Changes
- [ ] bot 已經出現在 Server 成員列表
- [ ] 專案資料夾有 `.env`，四個項目都填了值
- [ ] 在專案資料夾執行 `git status`，**沒有**看到 `.env`（代表被擋住了）
- [ ] token 沒有貼在其他任何地方

下一步：由 Claude Code 寫程式（P6）。
