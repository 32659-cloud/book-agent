"""排隊與限流：照片一張一張處理，避免同時開很多個 claude -p，也避免 Excel 同時被寫。"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import defaultdict, deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

log = logging.getLogger("book_agent.queue")


@dataclass
class Job:
    user_id: int
    user_name: str
    message: Any  # 使用者傳圖片的那則 Discord 訊息
    attachments: Any  # 那則訊息裡的圖片（最多 3 張，同一本書）
    wants_buy: bool  # 訊息文字有「想買」（由程式比對，不給模型）
    notice: Any = None  # 「處理中」那則回覆，處理完會被改成結果
    page: int | None = None  # 訊息文字寫的頁數（由程式比對，不給模型）


class JobQueue:
    def __init__(self, total_limit: int = 30, per_user_limit: int = 5, per_minute: int = 3):
        self.total_limit = total_limit
        self.per_user_limit = per_user_limit
        self.per_minute = per_minute
        self._queue: asyncio.Queue[Job] = asyncio.Queue()
        self._pending: defaultdict[int, int] = defaultdict(int)  # 每人排隊中的數量（含處理中）
        self._recent: defaultdict[int, deque[float]] = defaultdict(deque)  # 每人最近一分鐘送出的時間

    def reserve(self, user_id: int, now: float | None = None) -> str | None:
        """檢查這個人現在能不能再送一張，可以的話先佔一個位置。回傳 None 表示可以，否則是拒絕原因。"""
        now = time.monotonic() if now is None else now
        recent = self._recent[user_id]
        while recent and now - recent[0] >= 60:
            recent.popleft()
        if self._pending[user_id] >= self.per_user_limit:
            return f"你已經有 {self.per_user_limit} 張在排隊了，等處理完再傳。"
        if sum(self._pending.values()) >= self.total_limit:
            return "現在排隊的人太多了，請稍後再傳。"
        if len(recent) >= self.per_minute:
            return f"傳得太快了，每分鐘最多 {self.per_minute} 張，請稍等一下。"
        recent.append(now)
        self._pending[user_id] += 1
        return None

    def release(self, user_id: int) -> None:
        self._pending[user_id] = max(0, self._pending[user_id] - 1)

    def enqueue(self, job: Job) -> None:
        self._queue.put_nowait(job)

    async def run(self, process: Callable[[Job], Awaitable[None]]) -> None:
        """只有這一個工作者，一次處理一張。"""
        while True:
            job = await self._queue.get()
            try:
                await process(job)
            except Exception:
                log.exception("處理照片時發生未預期的錯誤")
            finally:
                self.release(job.user_id)
                self._queue.task_done()
