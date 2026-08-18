# -*- coding: utf-8 -*-
"""向 _validate_lyrics 注入两个检测器：动机降维 + 符号过密。"""
p = "D:/software/code/ideas/list/aigc-studio/apps/api/app/api/v1/generations/music.py"
src = open(p, encoding="utf-8").read()

# 1) 在"段落单薄检测"之后、押韵提示之前插入两个新检测
anchor = """    # 押韵提示：任一段内句尾字完全相同的重复韵脚（如整段全押"光"）"""
inject = '''    # 人物动机降维检测：丧亲意象 + 反复守/等/留，但几乎没有职业/劳动动作 = 悲情覆盖价值
    # （人物价值层级坍缩：人物被悲伤解释吞掉，缺少信仰/使命/职业伦理支撑）
    _LOSS_WORDS = ("亡妻", "去世", "走丢", "没救上来", "牺牲", "不在了", "出的事", "翻船", "淋雨走丢")
    _LINGER_WORDS = ("守", "等", "留", "念")
    _LABOR_WORDS = (
        "修", "补", "焊", "扫", "检", "量", "算", "装", "卸", "递", "撑", "擦", "磨",
        "捡", "纳", "缝", "煮", "熬", "抄", "记", "值", "倒", "盛", "捞", "洗", "晾",
        "拆", "绑", "缠", "拧", "敲", "刮", "浇", "筑", "搬", "扛", "推", "铲", "刨",
    )
    loss_hits = [w for w in _LOSS_WORDS if w in text]
    linger_hits = [w for w in _LINGER_WORDS if w in text]
    labor_hits = [w for w in _LABOR_WORDS if w in text]
    if loss_hits and len(linger_hits) >= 2 and len(labor_hits) <= 1:
        warnings.append(
            "人物动机降维（悲情覆盖价值）：出现丧亲意象（"
            + "、".join(loss_hits[:3])
            + "）+ 反复「守/等/留」，但全曲几乎没有职业/劳动动作——"
            "人物被悲伤解释吞掉，加职业逻辑与具体劳动细节（修/补/检/扫/煮…），"
            "让创伤成为信仰的起点而非动机的全部"
        )
    # 符号过密检测：意象全在第一联想语义空间（雨=思念/桥=人生/旧物=回忆）
    _SYMBOL_WORDS = (
        "雨", "桥", "伞", "灯", "旧", "故人", "十年", "远方", "霜", "青瓦", "江南", "烟雨", "风",
    )
    symbol_hits = [w for w in _SYMBOL_WORDS if w in text]
    if len(symbol_hits) >= 6:
        warnings.append(
            "符号过密（"
            + "、".join(symbol_hits[:6])
            + "）：意象全在第一联想语义空间，换现实/职业/技术维度；"
            "物件首先是物件，意义从使用中涌现"
        )

    # 押韵提示：任一段内句尾字完全相同的重复韵脚（如整段全押"光"）'''

assert anchor in src, "anchor not found"
src = src.replace(anchor, inject, 1)

# 2) _severe_checks 加入"降维"和"符号过密"
severe_old = '        or ("偏短/单薄" in c)'
severe_new = (
    '        or ("偏短/单薄" in c)\n'
    '        or ("动机降维" in c)\n'
    '        or ("符号过密" in c)'
)
assert severe_old in src, "severe anchor not found"
src = src.replace(severe_old, severe_new, 1)

open(p, "w", encoding="utf-8").write(src)
print("OK: detectors injected")
