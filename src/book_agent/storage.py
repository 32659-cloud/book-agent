"""書單 Excel 與照片存放。

防護 3（清洗檔名）與防護 4（防止 Excel 公式注入）的程式在這個檔案。
每一段防護都放在函式裡、用註解標出開始與結束，整段註解掉後程式仍能執行（只是不再有防護）。
"""

from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from openpyxl import Workbook, load_workbook

CATEGORIES = [
    "文學小說",
    "商業理財",
    "心理勵志",
    "科學科普",
    "人文社科",
    "語言學習",
    "電腦資訊",
    "藝術設計",
    "漫畫輕小說",
    "生活健康",
    "其他",
]

HEADERS = [
    "編號",
    "日期時間",
    "上傳者ID",
    "上傳者名稱",
    "書名",
    "作者",
    "類別",
    "閱讀狀態",
    "購買狀態",
    "是否已刪除",
    "照片存放位置",
    "目前頁數",  # 後來才加的欄位，放在最後，舊的 books.xlsx 也能繼續用
]
MAX_PAGE = 99999
COL = {name: i + 1 for i, name in enumerate(HEADERS)}

UNREAD, READ = "未讀", "已讀"
BOUGHT, NOT_BOUGHT = "已購買", "未購買"
DELETED = "已刪除"

TITLE_MAX = 100
AUTHOR_MAX = 60

_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")
_WINDOWS_RESERVED = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


class StorageBusyError(Exception):
    """Excel 一直寫不進去（通常是檔案正被打開）。"""


@dataclass
class Book:
    number: int
    created: str
    user_id: str
    user_name: str
    title: str
    author: str
    category: str
    read: str
    bought: str
    deleted: bool
    photo: str
    page: int = 0  # 讀到第幾頁，0 表示沒記錄


def clean_text(value: object, max_len: int) -> str:
    """去掉控制字元、合併空白、截斷長度。"""
    s = _CONTROL_CHARS.sub(" ", str(value if value is not None else ""))
    s = re.sub(r"\s+", " ", s).strip()
    return s[:max_len].strip()


def plain(value: object) -> str:
    """把 Excel 儲存格讀回一般文字（拿掉防護 4 加上去的單引號）。"""
    s = "" if value is None else str(value)
    if len(s) > 1 and s[0] == "'" and s[1] in "=+-@":
        return s[1:]
    return s


def safe_filename_part(name: str, max_len: int = 20) -> str:
    """把書名變成可以放進檔名的一小段文字。"""
    s = _CONTROL_CHARS.sub("_", str(name))
    # ==== 防護 3：清洗檔名　開始 ====
    s = re.sub(r'[\\/:*?"<>|]', "_", s)  # 路徑與 Windows 不能用的字元
    s = s.replace("..", "_")  # 往上一層資料夾
    s = s.strip(" .")  # Windows 不允許結尾是空白或點
    s = s[:max_len].strip(" .")
    if s.upper() in _WINDOWS_RESERVED:
        s = f"_{s}"
    # ==== 防護 3 結束 ====
    return s or "未命名"


def set_text_cell(cell, value: object, max_len: int = 200) -> None:
    """把文字寫進儲存格，並確保 Excel 把它當成純文字。"""
    text = clean_text(value, max_len)
    # ==== 防護 4：防止 Excel 公式注入　開始 ====
    if text[:1] in ("=", "+", "-", "@"):
        text = "'" + text  # 開頭是公式符號：前面加單引號
    cell.value = text
    cell.data_type = "s"  # 明確標成文字，不讓 openpyxl 當成公式
    # ==== 防護 4 結束 ====


def _norm(s: str) -> str:
    return re.sub(r"\s+", "", s).casefold()


class BookStore:
    def __init__(self, data_dir: Path | str):
        self.data_dir = Path(data_dir).resolve()
        self.xlsx = self.data_dir / "books.xlsx"
        self.photo_dir = self.data_dir / "photos"
        self.photo_dir.mkdir(parents=True, exist_ok=True)

    # ---- Excel 讀寫 ----

    def _open(self):
        if self.xlsx.exists():
            wb = load_workbook(self.xlsx)
            ws = wb["書單"]
            for name, col in COL.items():  # 舊檔案缺少的欄位標題補上
                if ws.cell(row=1, column=col).value is None:
                    ws.cell(row=1, column=col).value = name
            return wb, ws
        wb = Workbook()
        ws = wb.active
        ws.title = "書單"
        ws.append(HEADERS)
        return wb, ws

    def _save(self, wb, retries: int = 15, wait: float = 2.0) -> None:
        """先存成暫存檔再換掉正式檔；檔案被打開時印警告並重試。"""
        tmp = self.xlsx.with_name("books.xlsx.tmp")
        for attempt in range(1, retries + 1):
            try:
                wb.save(tmp)
                os.replace(tmp, self.xlsx)
                return
            except PermissionError:
                # flush=True：輸出被導到檔案或在背景執行時，也要馬上看得到
                print(
                    f"[警告] books.xlsx 好像正被打開，無法寫入（第 {attempt}/{retries} 次），{wait:.0f} 秒後重試",
                    flush=True,
                )
                time.sleep(wait)
        tmp.unlink(missing_ok=True)
        raise StorageBusyError("books.xlsx 一直無法寫入")

    @staticmethod
    def _to_book(ws, row: int) -> Book:
        def v(name):
            return ws.cell(row=row, column=COL[name]).value

        raw_page = v("目前頁數")
        page = raw_page if isinstance(raw_page, int) and 0 <= raw_page <= MAX_PAGE else 0
        return Book(
            number=int(v("編號") or 0),
            created=plain(v("日期時間")),
            user_id=plain(v("上傳者ID")),
            user_name=plain(v("上傳者名稱")),
            title=plain(v("書名")),
            author=plain(v("作者")),
            category=plain(v("類別")),
            read=plain(v("閱讀狀態")) or UNREAD,
            bought=plain(v("購買狀態")) or BOUGHT,
            deleted=plain(v("是否已刪除")) == DELETED,
            photo=plain(v("照片存放位置")),
            page=page,
        )

    def _user_rows(self, ws, user_id) -> list[tuple[int, Book]]:
        uid = str(user_id)
        out = []
        for row in range(2, ws.max_row + 1):
            if ws.cell(row=row, column=COL["編號"]).value is None:
                continue
            book = self._to_book(ws, row)
            if book.user_id == uid:
                out.append((row, book))
        return out

    # ---- 書單操作（全部只動這個 user_id 自己的列）----

    def list_books(self, user_id) -> list[Book]:
        _, ws = self._open()
        books = [b for _, b in self._user_rows(ws, user_id) if not b.deleted]
        return sorted(books, key=lambda b: b.number)

    def get_book(self, user_id, number: int) -> Book | None:
        return next((b for b in self.list_books(user_id) if b.number == number), None)

    def find_duplicate(self, user_id, title: str, author: str) -> Book | None:
        key = (_norm(title), _norm(author))
        for b in self.list_books(user_id):
            if (_norm(b.title), _norm(b.author)) == key:
                return b
        return None

    def add_book(
        self,
        user_id,
        user_name: str,
        title: str,
        author: str,
        category: str,
        bought: bool,
        photo: str,
        now: datetime | None = None,
        page: int = 0,
    ) -> Book:
        wb, ws = self._open()
        rows = self._user_rows(ws, user_id)  # 含已刪除的，編號不重複使用
        number = max((b.number for _, b in rows), default=0) + 1
        now = now or datetime.now()
        values = {
            "日期時間": now.strftime("%Y-%m-%d %H:%M:%S"),
            "上傳者ID": str(user_id),
            "上傳者名稱": user_name,
            "書名": title,
            "作者": author,
            "類別": category if category in CATEGORIES else "其他",
            "閱讀狀態": UNREAD,
            "購買狀態": BOUGHT if bought else NOT_BOUGHT,
            "是否已刪除": "",
            "照片存放位置": photo,
        }
        row = ws.max_row + 1
        ws.cell(row=row, column=COL["編號"]).value = number
        ws.cell(row=row, column=COL["目前頁數"]).value = page if isinstance(page, int) and 0 <= page <= MAX_PAGE else 0
        for name, value in values.items():
            set_text_cell(ws.cell(row=row, column=COL[name]), value, TITLE_MAX if name == "書名" else 200)
        self._save(wb)
        return self._to_book(ws, row)

    def update_field(self, user_id, number: int, field: str, value: str) -> Book | None:
        """修改某本書的某一欄；找不到（或已刪除）回傳 None。"""
        wb, ws = self._open()
        for row, book in self._user_rows(ws, user_id):
            if book.number == number and not book.deleted:
                set_text_cell(ws.cell(row=row, column=COL[field]), value, TITLE_MAX)
                self._save(wb)
                return self._to_book(ws, row)
        return None

    def set_page(self, user_id, number: int, page: int) -> Book | None:
        """記錄讀到第幾頁（0 = 清除）。頁數是整數，直接寫入數字格，不是文字。"""
        if not isinstance(page, int) or isinstance(page, bool) or not 0 <= page <= MAX_PAGE:
            raise ValueError("頁數超出範圍")
        wb, ws = self._open()
        for row, book in self._user_rows(ws, user_id):
            if book.number == number and not book.deleted:
                ws.cell(row=row, column=COL["目前頁數"]).value = page
                self._save(wb)
                return self._to_book(ws, row)
        return None

    def mark_deleted(self, user_id, number: int) -> Book | None:
        return self.update_field(user_id, number, "是否已刪除", DELETED)

    def stats(self, user_id) -> dict:
        books = self.list_books(user_id)
        by_category: dict[str, int] = {}
        for b in books:
            by_category[b.category] = by_category.get(b.category, 0) + 1
        return {
            "total": len(books),
            "read": sum(b.read == READ for b in books),
            "reading": sum(b.read != READ and b.page > 0 for b in books),  # 有記頁數、還沒標已讀
            "unread": sum(b.read != READ and b.page == 0 for b in books),
            "bought": sum(b.bought == BOUGHT for b in books),
            "not_bought": sum(b.bought != BOUGHT for b in books),
            "by_category": by_category,
        }

    # ---- 照片 ----

    def save_photo(self, user_id, title: str, ext: str, data: bytes, now: datetime | None = None) -> str:
        """存照片，回傳相對於 DATA_DIR 的路徑（用 / 分隔）。"""
        if not str(user_id).isdigit():
            raise ValueError("user_id 必須是數字")
        user_dir = self.photo_dir / str(user_id)
        user_dir.mkdir(parents=True, exist_ok=True)
        stamp = (now or datetime.now()).strftime("%Y-%m-%d %H-%M-%S")
        base = f"{stamp} {safe_filename_part(title)}"
        target = user_dir / f"{base}{ext}"
        n = 2
        while target.exists():  # 同一秒撞名
            target = user_dir / f"{base}-{n}{ext}"
            n += 1
        # ==== 防護 3：確認檔案真的落在這個人的照片資料夾裡　開始 ====
        if user_dir.resolve() not in target.resolve().parents:
            raise ValueError("檔案路徑超出照片資料夾")
        # ==== 防護 3 結束 ====
        target.write_bytes(data)
        return target.relative_to(self.data_dir).as_posix()
