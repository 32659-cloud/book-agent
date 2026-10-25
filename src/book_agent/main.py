"""啟動 Discord bot：收訊息、排隊、辨識、記錄、回覆。"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from dataclasses import dataclass
from pathlib import Path

import discord
from dotenv import load_dotenv

from .commands import HELP_MARKER, HELP_TEXT, handle_command, parse_page, read_status
from .queue_worker import Job, JobQueue
from .storage import BookStore, StorageBusyError
from .vision import (
    MAX_IMAGE_BYTES,
    MAX_IMAGES,
    AnalysisFailed,
    NotABook,
    Unreadable,
    analyze_images,
    detect_image_ext,
)

log = logging.getLogger("book_agent")

MESSAGE_LIMIT = 1900  # Discord 單則訊息上限 2000 字，留一點空間


@dataclass
class Config:
    token: str
    channel_id: int
    model: str
    data_dir: Path


def load_config() -> Config:
    load_dotenv()
    token = os.getenv("DISCORD_TOKEN", "").strip()
    channel = os.getenv("CHANNEL_ID", "").strip()
    if not token or not channel.isdigit():
        sys.exit("請先在 .env 設定 DISCORD_TOKEN 和 CHANNEL_ID（見 docs/discord-bot-setup.md）")
    return Config(
        token=token,
        channel_id=int(channel),
        model=os.getenv("CLAUDE_MODEL", "haiku").strip() or "haiku",
        data_dir=Path(os.getenv("DATA_DIR", "./data")),
    )


def _is_image(a: discord.Attachment) -> bool:
    if a.content_type and a.content_type.startswith("image/"):
        return True
    return a.filename.lower().endswith((".png", ".jpg", ".jpeg", ".webp", ".gif"))


def _clip(text: str) -> str:
    return text if len(text) <= MESSAGE_LIMIT else text[: MESSAGE_LIMIT - 1] + "…"


class BookClient(discord.Client):
    def __init__(self, cfg: Config):
        intents = discord.Intents.default()
        intents.message_content = True  # 要讀指令和「想買」，必須打開
        # 回覆裡有書名等外部內容，一律不讓它 @ 任何人
        super().__init__(intents=intents, allowed_mentions=discord.AllowedMentions.none())
        self.cfg = cfg
        self.store = BookStore(cfg.data_dir)
        self.jobs = JobQueue()
        self.lock = asyncio.Lock()  # 所有讀寫 Excel 的動作一次只做一個
        self._ready_once = False

    async def setup_hook(self) -> None:
        self._worker = asyncio.create_task(self.jobs.run(self.process_job))

    async def on_ready(self) -> None:
        log.info("已登入為 %s，只聽頻道 %s", self.user, self.cfg.channel_id)
        if not self._ready_once:
            self._ready_once = True
            await self.post_help()

    async def post_help(self) -> None:
        """在頻道發使用說明並置頂；已經有舊的置頂說明就改內容，不重複發。"""
        try:
            channel = self.get_channel(self.cfg.channel_id) or await self.fetch_channel(self.cfg.channel_id)
            async for pinned in channel.pins():
                if pinned.author == self.user and pinned.content.startswith(HELP_MARKER):
                    if pinned.content != HELP_TEXT:
                        await pinned.edit(content=HELP_TEXT)
                    return
            msg = await channel.send(HELP_TEXT)
            await msg.pin()
        except discord.HTTPException as e:
            log.warning("發佈或置頂使用說明失敗（檢查 bot 的「釘選訊息」權限）：%s", e)

    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot or message.channel.id != self.cfg.channel_id:
            return  # 只聽指定頻道；其他頻道一律不理
        images = [a for a in message.attachments if _is_image(a)]
        if images:
            await self.handle_photo(message, images[:MAX_IMAGES])  # 一則訊息最多看 3 張，當成同一本書
        elif message.content.strip().startswith("!"):
            await self.handle_command_message(message)

    # ---- 指令 ----

    async def handle_command_message(self, message: discord.Message) -> None:
        async with self.lock:
            reply = await asyncio.to_thread(
                handle_command,
                self.store,
                message.author.id,
                message.author.display_name,
                message.content,
            )
        await message.reply(_clip(reply), mention_author=False)

    # ---- 照片 ----

    async def handle_photo(self, message: discord.Message, attachments: list[discord.Attachment]) -> None:
        if any(a.size > MAX_IMAGE_BYTES for a in attachments):
            await message.reply("圖片太大了，每張請傳 8 MB 以內。", mention_author=False)
            return
        reason = self.jobs.reserve(message.author.id)
        if reason:
            await message.reply(reason, mention_author=False)
            return
        try:
            notice = await message.reply("⏳ 處理中…（排隊辨識）", mention_author=False)
        except discord.HTTPException:
            self.jobs.release(message.author.id)
            raise
        self.jobs.enqueue(
            Job(
                user_id=message.author.id,
                user_name=message.author.display_name,
                message=message,
                attachments=attachments,
                wants_buy="想買" in message.content,  # 由程式比對文字，文字不會交給模型
                notice=notice,
                page=parse_page(message.content),  # 同上：「第 84 頁」「84 頁」「84」由程式比對
            )
        )

    async def process_job(self, job: Job) -> None:
        try:
            text = await self._analyze_and_record(job)
        except Exception:
            log.exception("處理失敗")
            text = "處理時發生錯誤，請再傳一次。"
        text = _clip(text)
        try:
            await job.notice.edit(content=text)
        except discord.HTTPException:
            await job.message.reply(text, mention_author=False)

    async def _analyze_and_record(self, job: Job) -> str:
        images: list[tuple[bytes, str]] = []
        for attachment in job.attachments:
            data = await attachment.read()
            ext = detect_image_ext(data)
            if ext is None:
                return "這個圖片格式我看不懂，請傳 PNG、JPEG、WebP 或 GIF。"
            images.append((data, ext))
        try:
            info = await analyze_images(images, self.cfg.model, self.store.data_dir)
        except NotABook as e:
            return f"你傳的不是書，是{e.what_it_is}。"
        except Unreadable:
            return "看不清楚書名，請重拍一張（拍正、光線足夠、讓封面佔滿畫面）。"
        except AnalysisFailed:
            return "分析失敗，請再傳一次。"
        async with self.lock:
            # 照片只存第一張（通常是封面）
            return await asyncio.to_thread(self._record, job, info, images[0][0], images[0][1])

    def _record(self, job: Job, info, data: bytes, ext: str) -> str:
        dup = self.store.find_duplicate(job.user_id, info.title, info.author)
        if dup:
            text = f"《{dup.title}》已經在你的書單了（編號 {dup.number}），不重複新增。"
            if job.page:  # 重傳同一本書並寫了頁數：順便更新進度
                try:
                    self.store.set_page(job.user_id, dup.number, job.page)
                    text += f"\n已把進度更新為第 {job.page} 頁。"
                except StorageBusyError:
                    text += "\nbooks.xlsx 目前被占用，進度沒有更新，請關閉後用 `!進度` 再記一次。"
            return text
        photo = self.store.save_photo(job.user_id, info.title, ext, data)
        try:
            book = self.store.add_book(
                job.user_id,
                job.user_name,
                info.title,
                info.author,
                info.category,
                bought=not job.wants_buy,
                photo=photo,
                page=job.page or 0,
            )
        except StorageBusyError:
            (self.store.data_dir / photo).unlink(missing_ok=True)
            return "books.xlsx 目前被占用（可能正被打開），這次沒有記下來，請關閉後再傳一次。"
        s = self.store.stats(job.user_id)
        return (
            f"📚 已記到你的書單（編號 {book.number}）\n"
            f"書名：《{book.title}》\n"
            f"作者：{book.author or '作者不詳'}\n"
            f"類別：{book.category}\n"
            f"狀態：{read_status(book)}｜{book.bought}\n"
            f"你的書單共 {s['total']} 本，未讀 {s['unread']} 本，未購買 {s['not_bought']} 本"
        )


def run() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    cfg = load_config()
    BookClient(cfg).run(cfg.token, log_handler=None)  # log_handler=None：沿用上面的 logging 設定
