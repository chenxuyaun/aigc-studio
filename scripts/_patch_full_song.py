# -*- coding: utf-8 -*-
"""同步检测阈值到完整歌曲结构：偏短 400、副歌 2-3、段落句数。"""
p = "D:/software/code/ideas/list/aigc-studio/apps/api/app/api/v1/generations/music.py"
src = open(p, encoding="utf-8").read()

# 1) 偏短阈值 230 → 400，文案更新（demo 化）
old_short = (
    '    if 0 < len(text) < 230:\n'
    '        warnings.append(f"歌词偏短/单薄（{len(text)}字，建议 260-450）——内容密度不足："\n'
    '                        "短句化后细节全丢、只剩骨架，加长主歌句数与具体细节（物件/动作/声音）")'
)
new_short = (
    '    if 0 < len(text) < 400:\n'
    '        warnings.append(f"歌词太短（{len(text)}字，完整歌曲应 500-750 字）——这是 demo 不是完整歌："\n'
    '                        "补预副歌/加长主歌与副歌遍数/加厚细节（物件/动作/声音），让歌曲到 3-4 分钟")'
)
assert old_short in src, "short anchor not found"
src = src.replace(old_short, new_short, 1)

# 2) 副歌次数：2-3 次（>3 才报）
old_chorus = '    elif counts["【副歌】"] > 2:\n        warnings.append(f"副歌出现了 {counts[\'【副歌】\']} 次（应为 2 次）")'
new_chorus = '    elif counts["【副歌】"] > 3:\n        warnings.append(f"副歌出现了 {counts[\'【副歌】\']} 次（应为 2-3 次）")'
assert old_chorus in src, "chorus anchor not found"
src = src.replace(old_chorus, new_chorus, 1)

# 3) 段落单薄阈值：主歌 5、副歌 4、桥段 3（预副歌不强制，出现则要求 2 句）
old_para = (
    '    for tag, min_lines in (("【主歌1】", 4), ("【主歌2】", 4), ("【副歌】", 4), ("【桥段】", 3)):'
)
new_para = (
    '    for tag, min_lines in (("【主歌1】", 5), ("【主歌2】", 5), ("【副歌】", 4), ("【桥段】", 3), ("【预副歌】", 2)):'
)
assert old_para in src, "para anchor not found"
src = src.replace(old_para, new_para, 1)

open(p, "w", encoding="utf-8").write(src)
print("OK: thresholds synced to full-song structure")
