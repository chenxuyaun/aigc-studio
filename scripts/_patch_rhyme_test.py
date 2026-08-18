# -*- coding: utf-8 -*-
"""在 test_music_works.py 追加十三辙无韵检测测试。"""
p = "D:/software/code/ideas/list/aigc-studio/apps/api/tests/test_music_works.py"
src = open(p, encoding="utf-8").read()

test_block = '''

def test_validate_lyrics_flags_no_rhyme_by_thirteen_zhe() -> None:
    """十三辙押韵校验：句尾字全不同辙（言前/人辰/怀来/发花互不押）→ 无韵拦截；同辙不误报。"""
    from app.api.v1.generations.music import _severe_checks, _validate_lyrics

    # 句尾：山(言前) 门(人辰) 来(怀来) 下(发花) 停(中东) —— 5 字 5 辙全不同
    no_rhyme = """【主歌1】雨落渡口那座山
他靠在桥头看水门
风从江面吹过来
船桨横在石阶下
他数着日子等雨停
【副歌】他坐最低一档
等末班船过河
【主歌2】十年过去又一年
旧伞挂在竹竿边
【副歌】他坐最低一档
等末班船过河"""
    checks = _validate_lyrics(no_rhyme)
    assert any("无韵" in c for c in checks), "全不同辙句尾应判无韵"
    assert _severe_checks(checks), "无韵应触发自动重写"

    # 句尾同辙（言前：山/年/边/天）→ 不误报无韵
    rhymed = """【主歌1】雨落渡口那座山
他守着江水一年年
风从桥头吹过来
船桨横在石阶边
天没亮水线不断
像那年女儿走的那天
【副歌】他坐最低一档
等末班船过河
【主歌2】十年过去又一年
旧伞挂在竹竿边
【副歌】他坐最低一档
等末班船过河"""
    checks2 = _validate_lyrics(rhymed)
    assert not any("无韵" in c for c in checks2), "同辙押韵不应误报无韵"
'''

anchor = "\n\n# ---------- 风格检测与写歌质量闭环 ----------"
assert anchor in src, "anchor not found"
src = src.replace(anchor, test_block + "\n" + anchor, 1)
open(p, "w", encoding="utf-8").write(src)
print("OK: rhyme test added")
