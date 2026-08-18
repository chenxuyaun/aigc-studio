# -*- coding: utf-8 -*-
"""给 _CLEAN_LYRICS 加 3 句到 520+ 字。"""
t = "D:/software/code/ideas/list/aigc-studio/apps/api/tests/test_music_works.py"
tsrc = open(t, encoding="utf-8").read()

repl = [
    ('"路灯下他蹲着，把粥碗摆正\\n"\n',
     '"路灯下他蹲着，把粥碗摆正\\n"\n    "碗底那圈豁口，他拿胶布缠了三道\\n"\n'),
    ('"汽笛远了，他把灯调暗一档\\n"\n',
     '"汽笛远了，他把灯调暗一档\\n"\n    "灶台上的钟，走到四点差一刻\\n"\n'),
    ('"像那年她走时没说的那句话\\n"\n',
     '"像那年她走时没说的那句话\\n"\n    "信封上的邮戳，他看了二十年\\n"\n'),
]
for old, new in repl:
    assert old in tsrc, f"anchor not found: {old[:30]}"
    tsrc = tsrc.replace(old, new, 1)
open(t, "w", encoding="utf-8").write(tsrc)
print("OK: CLEAN_LYRICS thickened")
