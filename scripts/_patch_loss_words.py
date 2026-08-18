# -*- coding: utf-8 -*-
"""扩充动机降维检测的丧亲词表（口语说法）。"""
p = "D:/software/code/ideas/list/aigc-studio/apps/api/app/api/v1/generations/music.py"
src = open(p, encoding="utf-8").read()
old = '    _LOSS_WORDS = ("亡妻", "去世", "走丢", "没救上来", "牺牲", "不在了", "出的事", "翻船", "淋雨走丢")'
new = ('    _LOSS_WORDS = ("亡妻", "去世", "走丢", "没救上来", "牺牲", "不在了", "出的事", '
       '"翻船", "淋雨走丢", "再没回来", "走的那年", "没接住", "没等到")')
assert old in src, "not found"
src = src.replace(old, new, 1)
open(p, "w", encoding="utf-8").write(src)
print("OK: loss words expanded")
