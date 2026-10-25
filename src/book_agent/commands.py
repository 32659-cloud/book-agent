"""!書單、!未讀、!統計 等指令。全部由程式直接處理，不呼叫 claude -p。

每個指令只讀寫「傳指令的那個人自己」的書單（用 Discord user id 篩選）。
"""

from __future__ import annotations

import re

from .storage import (
    AUTHOR_MAX,
    BOUGHT,
    CATEGORIES,
    MAX_PAGE,
    NOT_BOUGHT,
    READ,
    TITLE_MAX,
    UNREAD,
    Book,
    BookStore,
    StorageBusyError,
    clean_text,
)

LIST_LIMIT = 10
HELP_MARKER = "【書單 agent 使用說明】"

HELP_TEXT = f"""{HELP_MARKER}
📷 **登錄書**：在這個頻道傳書的封面照片（網路書店截圖也可以），我會辨識書名、作者、類別，記到你自己的書單。
訊息裡加上「想買」兩個字，這本書會記成「未購買」（想買清單）。
訊息裡寫「第 84 頁」、「84 頁」或只寫「84」，會一起記下讀到第幾頁。
一則訊息最多可以傳 3 張圖（封面、書背、封底），我會一起看。

**指令**（只會動到你自己的書單）
編號：就是書單裡 # 後面的數字，例如 #3 的編號是 3。

`!書單`
　　最近 10 本；`!書單 類別` 或 `!書單 作者` 可以查詢
`!未讀`
　　還沒讀完的書（包含閱讀中）
`!未購買`
　　還沒買的書（想買清單）
`!已讀 編號`
　　切換閱讀完 / 未讀
`!進度 編號 頁數`
　　記錄讀到第幾頁（頁數填 0 可清除）
　　例：`!進度 3 120`
`!購買 編號`
　　切換已購買 / 未購買
`!統計`
　　各類別與狀態的數量
`!修正 編號 欄位 新內容`
　　辨識錯了就改。欄位只能填：書名、作者、類別（一次改一個）
　　例：`!修正 3 作者 村上春樹`
　　例：`!修正 3 類別 文學小說`（類別要從下面的類別選一個）
`!刪除 編號`
　　從書單移掉
`!說明`
　　再看一次這則說明

**類別**
　　{"、".join(CATEGORIES)}"""

EMPTY = "你的書單還是空的，先傳一張書的封面照片吧。"


_PAGE_PATTERNS = (
    re.compile(r"第\s*(\d{1,5})\s*頁"),  # 第84頁
    re.compile(r"(\d{1,5})\s*頁"),  # 84頁
    re.compile(r"^\s*(\d{1,5})\s*$"),  # 整則訊息只有數字：84
)


def parse_page(text: str) -> int | None:
    """從傳照片時附的文字找頁數。只認固定寫法，由程式比對，文字不會交給模型。"""
    for pattern in _PAGE_PATTERNS:
        m = pattern.search(text)
        if m:
            page = int(m.group(1))
            return page if 0 < page <= MAX_PAGE else None
    return None


def read_status(b: Book) -> str:
    """有記頁數、還沒標已讀的書，顯示為閱讀中。"""
    if b.read != READ and b.page > 0:
        return f"閱讀中（第 {b.page} 頁）"
    return "閱讀完" if b.read == READ else b.read  # Excel 裡存的還是「已讀」，只改顯示


INDENT = "　　"  # 全形空白：Discord 不會把它吃掉，欄位才會左邊對齊
LIST_CHAR_BUDGET = 1700  # 一則訊息上限 2000 字，留空間給標題與結尾


def _format_book(b: Book) -> str:
    """一本書分成四行：編號與書名、作者、類別、狀態。"""
    return (
        f"#{b.number} 《{b.title}》\n"
        f"{INDENT}作者：{b.author or '作者不詳'}\n"
        f"{INDENT}類別：{b.category}\n"
        f"{INDENT}狀態：{read_status(b)}｜{b.bought}"
    )


def _format_list(header: str, books: list[Book]) -> str:
    if not books:
        return f"{header}\n（沒有符合的書）"
    newest_first = sorted(books, key=lambda b: b.number, reverse=True)[:LIST_LIMIT]
    shown, used = [], len(header)
    for b in newest_first:  # 先挑出「最近的幾本」
        block = _format_book(b)
        if shown and used + len(block) + 2 > LIST_CHAR_BUDGET:  # 書名很長時少顯示幾本，不讓訊息被截斷
            break
        shown.append(block)
        used += len(block) + 2
    shown.reverse()  # 顯示時編號由小到大
    note = f"（只顯示最近 {len(shown)} 本，較早的 {len(books) - len(shown)} 本沒顯示）\n\n" if len(books) > len(shown) else ""
    return header + "\n\n" + note + "\n\n".join(shown)


def _parse_number(s: str) -> int | None:
    return int(s) if re.fullmatch(r"\d{1,6}", s) else None


def handle_command(store: BookStore, user_id: int, user_name: str, text: str) -> str:
    """text 以 ! 開頭。回傳要回覆的文字。"""
    parts = text.strip().split(maxsplit=1)
    cmd = parts[0]
    arg = parts[1].strip() if len(parts) > 1 else ""
    try:
        if cmd == "!說明":
            return HELP_TEXT
        if cmd == "!書單":
            return _cmd_list(store, user_id, arg)
        if cmd == "!未讀":
            books = [b for b in store.list_books(user_id) if b.read != READ]
            return _format_list(f"📖 {user_name} 還沒讀完的書（共 {len(books)} 本）", books)
        if cmd == "!未購買":
            books = [b for b in store.list_books(user_id) if b.bought != BOUGHT]
            return _format_list(f"🛒 {user_name} 的想買清單（共 {len(books)} 本）", books)
        if cmd == "!已讀":
            return _cmd_toggle(store, user_id, arg, "閱讀狀態", "read", READ, UNREAD)
        if cmd == "!購買":
            return _cmd_toggle(store, user_id, arg, "購買狀態", "bought", BOUGHT, NOT_BOUGHT)
        if cmd == "!進度":
            return _cmd_progress(store, user_id, arg)
        if cmd == "!統計":
            return _cmd_stats(store, user_id, user_name)
        if cmd == "!修正":
            return _cmd_fix(store, user_id, arg)
        if cmd == "!刪除":
            return _cmd_delete(store, user_id, arg)
    except StorageBusyError:
        return "books.xlsx 目前被占用（可能正被打開），請關閉後再試一次。"
    return "不認得這個指令，打 `!說明` 看有哪些。"


def _cmd_list(store: BookStore, user_id: int, arg: str) -> str:
    books = store.list_books(user_id)
    if not books:
        return EMPTY
    if not arg:
        return _format_list(f"📚 你的書單（共 {len(books)} 本）", books)
    key = arg.casefold()
    if arg in CATEGORIES:
        found = [b for b in books if b.category == arg]
    else:
        found = [b for b in books if key in b.author.casefold()]
    return _format_list(f"📚 「{clean_text(arg, 30)}」的結果（共 {len(found)} 本）", found)


def _cmd_toggle(store, user_id, arg, field, attr, on_value, off_value) -> str:
    number = _parse_number(arg)
    if number is None:
        return f"請加上編號，例如 `!{'已讀' if attr == 'read' else '購買'} 3`。"
    book = store.get_book(user_id, number)
    if book is None:
        return f"你的書單裡沒有編號 {number}。"
    new_value = off_value if getattr(book, attr) == on_value else on_value
    updated = store.update_field(user_id, number, field, new_value)
    return f"已更新\n{_format_book(updated)}"


def _cmd_progress(store: BookStore, user_id: int, arg: str) -> str:
    usage = f"用法：`!進度 編號 頁數`，例如 `!進度 3 120`（頁數 0 到 {MAX_PAGE}，填 0 清除）。"
    parts = arg.split()
    if len(parts) != 2:
        return usage
    number, page = _parse_number(parts[0]), _parse_number(parts[1])
    if number is None or page is None or page > MAX_PAGE:
        return usage
    updated = store.set_page(user_id, number, page)
    if updated is None:
        return f"你的書單裡沒有編號 {number}。"
    return f"已記錄\n{_format_book(updated)}"


def _cmd_stats(store: BookStore, user_id: int, user_name: str) -> str:
    s = store.stats(user_id)
    if s["total"] == 0:
        return EMPTY
    cats = "\n".join(
        f"{INDENT}{c}：{n} 本" for c, n in sorted(s["by_category"].items(), key=lambda kv: -kv[1])
    )
    return (
        f"📊 {user_name} 的書單統計\n\n"
        f"共計：{s['total']} 本\n"
        f"閱讀：閱讀完 {s['read']}／閱讀中 {s['reading']}／未讀 {s['unread']}\n"
        f"購買：已購買 {s['bought']}／未購買 {s['not_bought']}\n\n"
        f"類別\n{cats}"
    )


def _cmd_fix(store: BookStore, user_id: int, arg: str) -> str:
    usage = (
        "用法：`!修正 編號 欄位 新內容`\n"
        "欄位只能填：書名、作者、類別（一次改一個）\n"
        "例：`!修正 3 作者 村上春樹`"
    )
    parts = arg.split(maxsplit=2)
    if len(parts) < 3:
        return usage
    number = _parse_number(parts[0])
    field, value = parts[1], parts[2]
    if number is None or field not in ("書名", "作者", "類別"):
        return usage
    if store.get_book(user_id, number) is None:
        return f"你的書單裡沒有編號 {number}。"
    if field == "類別":
        value = value.strip()
        if value not in CATEGORIES:
            return "類別必須是：" + "、".join(CATEGORIES)
    else:
        value = clean_text(value, TITLE_MAX if field == "書名" else AUTHOR_MAX)
        if not value:
            return "新內容不能是空的。"
    updated = store.update_field(user_id, number, field, value)
    return f"已修正\n{_format_book(updated)}"


def _cmd_delete(store: BookStore, user_id: int, arg: str) -> str:
    number = _parse_number(arg)
    if number is None:
        return "請加上編號，例如 `!刪除 3`。"
    deleted = store.mark_deleted(user_id, number)
    if deleted is None:
        return f"你的書單裡沒有編號 {number}。"
    return f"已從書單移掉：#{number}《{deleted.title}》（Excel 裡仍保留紀錄）"
