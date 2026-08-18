# -*- coding: utf-8 -*-
"""在 _severe_checks 中加入偏短/单薄关键词。"""
import io
import sys

p = "D:/software/code/ideas/list/aigc-studio/apps/api/app/api/v1/generations/music.py"
src = open(p, encoding="utf-8").read()

old = '        or ("长句" in c)\n        or ("废稿" in c)'
new = (
    '        or ("长句" in c)\n'
    '        or ("偏短/单薄" in c)\n'
    '        or ("单薄" in c)\n'
    '        or ("废稿" in c)'
)
if old in src:
    src = src.replace(old, new, 1)
    open(p, "w", encoding="utf-8").write(src)
    print("OK: severe_checks updated")
else:
    idx = src.find('or ("长句" in c)')
    print("NOT FOUND, context:", repr(src[idx - 60:idx + 120]))
