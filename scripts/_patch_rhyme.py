# -*- coding: utf-8 -*-
"""押韵偷懒阈值：句尾字重复 ≥3 次才报（hook 三遍递进同尾字是设计，非偷懒）。"""
p = "D:/software/code/ideas/list/aigc-studio/apps/api/app/api/v1/generations/music.py"
src = open(p, encoding="utf-8").read()
old = "        dup = {t for t in tails if tails.count(t) > 1}"
new = "        dup = {t for t in tails if tails.count(t) >= 3}"
assert old in src, "anchor not found"
src = src.replace(old, new, 1)
open(p, "w", encoding="utf-8").write(src)
print("OK: rhyme laziness threshold >=3")
