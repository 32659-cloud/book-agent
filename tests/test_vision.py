import json
import string

import pytest

from book_agent.vision import (
    PROMPT_TEMPLATE,
    AnalysisFailed,
    NotABook,
    Unreadable,
    detect_image_ext,
    parse_result,
)


def j(**kw):
    base = {"is_book": True, "legible": True, "title": "書", "author": "我", "category": "文學小說", "what_it_is": ""}
    base.update(kw)
    return json.dumps(base, ensure_ascii=False)


def test_valid_result():
    info = parse_result(j(title="  海邊的卡夫卡 "))
    assert (info.title, info.author, info.category) == ("海邊的卡夫卡", "我", "文學小說")


def test_json_wrapped_in_code_fence_is_accepted():
    assert parse_result("```json\n" + j() + "\n```").title == "書"


@pytest.mark.parametrize(
    "text",
    ["", "沒有 json", "{壞掉", "[1,2]", j(is_book="yes"), j(legible=1), j(title=123), j(author=None), '{"is_book": true}'],
)
def test_bad_output_raises_analysis_failed_not_crash(text):
    with pytest.raises(AnalysisFailed):
        parse_result(text)


def test_not_a_book_and_unreadable():
    with pytest.raises(NotABook) as e:
        parse_result(j(is_book=False, what_it_is="馬克杯"))
    assert e.value.what_it_is == "馬克杯"
    with pytest.raises(Unreadable):
        parse_result(j(legible=False))
    with pytest.raises(Unreadable):
        parse_result(j(title="   "))


def test_unknown_category_and_long_values_are_normalised():
    info = parse_result(j(category="亂寫", title="長" * 500, author="長" * 500))
    assert info.category == "其他"
    assert len(info.title) == 100 and len(info.author) == 60


def test_detect_image_ext():
    assert detect_image_ext(b"\x89PNG\r\n\x1a\n....") == ".png"
    assert detect_image_ext(b"\xff\xd8\xff\xe0....") == ".jpg"
    assert detect_image_ext(b"RIFF\x00\x00\x00\x00WEBPxxxx") == ".webp"
    assert detect_image_ext(b"GIF89a....") == ".gif"
    assert detect_image_ext(b"MZ\x90\x00 evil.exe") is None


def test_prompt_only_has_program_controlled_fields():
    # 防護 2：模板裡只有程式決定的 paths 與 categories 兩個欄位，沒有使用者文字的欄位
    fields = {f for _, f, _, _ in string.Formatter().parse(PROMPT_TEMPLATE) if f}
    assert fields == {"paths", "categories"}


def test_analyze_images_rejects_zero_or_too_many_or_oversized():
    import asyncio
    from pathlib import Path

    from book_agent.vision import MAX_IMAGE_BYTES, MAX_IMAGES, analyze_images

    ok = (b"\x89PNG\r\n\x1a\n", ".png")
    for bad in ([], [ok] * (MAX_IMAGES + 1), [(b"x" * (MAX_IMAGE_BYTES + 1), ".png")]):
        with pytest.raises(AnalysisFailed):
            asyncio.run(analyze_images(bad, "haiku", Path(".")))


def test_protection_1_command_isolates_claude(tmp_path, monkeypatch):
    # 防護 1：實測過 --allowedTools Read 會允許讀整台電腦，所以絕對不能出現；
    # 要在照片專屬的暫存資料夾裡執行，而且拿不到 DISCORD_TOKEN
    from book_agent.vision import build_command

    monkeypatch.setenv("DISCORD_TOKEN", "secret")
    work, data = tmp_path / "work", tmp_path / "data"
    cmd, cwd, env = build_command("claude", "p", "haiku", work, data)
    assert cwd == work
    assert "--allowedTools" not in cmd and "--allowed-tools" not in cmd
    assert cmd[cmd.index("--tools") + 1] == "Read"
    assert cmd[cmd.index("--permission-mode") + 1] == "dontAsk"
    assert "DISCORD_TOKEN" not in env
