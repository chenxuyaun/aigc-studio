"""状态批注账本：解析/剥离/合并/冲突检查。"""

from __future__ import annotations

from app.services.status_book import (
    apply_book,
    book_to_text,
    parse_annotations,
    strip_annotations,
)


def test_parse_annotations_variants():
    text = (
        "老周把药瓶放下。//**老周[伤势]：左臂轻伤 -> 已恢复**\n"
        "翠翠笑了笑。//**翠翠[心情]：平静**\n"
        "//**老陈[工钱]：欠三个月 ⇒ 还清了**"
    )
    anns = parse_annotations(text)
    assert len(anns) == 3
    assert anns[0] == {"character": "老周", "category": "伤势", "old": "左臂轻伤", "new": "已恢复"}
    # 无旧值（直接登记）
    assert anns[1]["old"] == "" and anns[1]["new"] == "平静"
    assert anns[2]["new"] == "还清了"


def test_strip_annotations_removes_all():
    text = "他点了点头。//**老周[伤势]：轻伤 -> 已恢复** 继续向前。"
    assert strip_annotations(text) == "他点了点头。 继续向前。"


def test_apply_book_and_conflict():
    book = {"老周": {"伤势": "左臂轻伤"}}
    book, warnings = apply_book(book, [
        {"character": "老周", "category": "伤势", "old": "左臂轻伤", "new": "已恢复"},
        {"character": "老周", "category": "伤势", "old": "旧伤", "new": "复发"},
    ])
    assert book["老周"]["伤势"] == "复发"
    assert any("冲突" in w for w in warnings), warnings


def test_book_to_text_format():
    book = {"老周": {"伤势": "已恢复"}, "翠翠": {}}
    text = book_to_text(book)
    assert "老周" in text and "伤势=已恢复" in text
    assert "翠翠" not in text  # 空类别不输出
