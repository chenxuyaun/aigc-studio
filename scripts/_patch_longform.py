# -*- coding: utf-8 -*-
"""检测同步长曲结构：偏短 700、段落加主歌3。"""
p = "D:/software/code/ideas/list/aigc-studio/apps/api/app/api/v1/generations/music.py"
src = open(p, encoding="utf-8").read()

old_short = (
    '    if 0 < len(text) < 400:\n'
    '        warnings.append(f"歌词太短（{len(text)}字，完整歌曲应 500-750 字）——这是 demo 不是完整歌："\n'
    '                        "补预副歌/加长主歌与副歌遍数/加厚细节（物件/动作/声音），让歌曲到 3-4 分钟")'
)
new_short = (
    '    if 0 < len(text) < 700:\n'
    '        warnings.append(f"歌词偏短（{len(text)}字，完整长曲应 900-1100 字两段式）——这是短版不是长曲："\n'
    '                        "补【主歌3】/加长主歌句数与副歌遍数/加厚细节（物件/动作/声音），Part A+B 合计到 5-6 分钟")'
)
assert old_short in src, "short anchor not found"
src = src.replace(old_short, new_short, 1)

old_para = (
    '    for tag, min_lines in (("【主歌1】", 5), ("【主歌2】", 5), ("【副歌】", 4), ("【桥段】", 3), ("【预副歌】", 2)):'
)
new_para = (
    '    for tag, min_lines in (("【主歌1】", 5), ("【主歌2】", 5), ("【主歌3】", 4), ("【副歌】", 4), ("【桥段】", 3), ("【预副歌】", 2)):'
)
assert old_para in src, "para anchor not found"
src = src.replace(old_para, new_para, 1)

open(p, "w", encoding="utf-8").write(src)
print("OK: thresholds -> long-form (700 / 主歌3)")
