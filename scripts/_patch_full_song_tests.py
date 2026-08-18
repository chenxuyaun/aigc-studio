# -*- coding: utf-8 -*-
"""①severe 加"太短"；②加厚 _CLEAN_LYRICS 到完整歌 410+ 字。"""
p = "D:/software/code/ideas/list/aigc-studio/apps/api/app/api/v1/generations/music.py"
src = open(p, encoding="utf-8").read()
old = '        or ("偏短/单薄" in c)'
new = '        or ("偏短/单薄" in c)\n        or ("太短" in c)'
assert old in src, "severe anchor not found"
src = src.replace(old, new, 1)
open(p, "w", encoding="utf-8").write(src)
print("OK: severe includes 太短")

t = "D:/software/code/ideas/list/aigc-studio/apps/api/tests/test_music_works.py"
tsrc = open(t, encoding="utf-8").read()
old_clean = '''_CLEAN_LYRICS = (
    "【主歌1】天没亮，路灯下卖粥的掀开锅盖\\n"
    "白汽扑上玻璃，糊了半扇窗\\n"
    "他把米汤撇进桶，锅底刮三遍\\n"
    "末班车过站台，灯晃了一下\\n"
    "那年她也坐这班，多看了两眼\\n"
    "粥勺磕在缸沿，响一声数一声\\n"
    "【副歌】雾漫过山脊，我端着碗等天亮\\n"
    "锅盖响了三声，他说多添碗汤\\n"
    "汽笛穿过巷口，她还没回来\\n"
    "他把粥温着，像温着一句话\\n"
    "【主歌2】收摊时剩粥倒给流浪猫\\n"
    "猫不来，粥凉在桶里没人喝\\n"
    "早班车灯扫过，他背过身擦碗\\n"
    "街对过那盏灯，昨晚还亮着\\n"
    "保温杯搁在挡位旁，茶垢一圈圈\\n"
    "他数着日子，像数粥里的米粒\\n"
    "【桥段】他说，明天还来，天总会亮的\\n"
    "抹布搭在缸沿，像个人还在等\\n"
    "那碗粥凉了又热，热了又凉\\n"
    "【副歌】雾漫过山脊，我端着碗等天亮\\n"
    "锅盖响了三声，他说多添碗汤\\n"
    "汽笛穿过巷口，她还没回来\\n"
    "他把粥温着，像温着一句话"
)'''
new_clean = '''_CLEAN_LYRICS = (
    "【主歌1】天没亮，路灯下卖粥的掀开锅盖\\n"
    "白汽扑上玻璃，糊了半扇窗\\n"
    "他把米汤撇进桶，锅底刮三遍\\n"
    "末班车过站台，灯晃了一下\\n"
    "那年她也坐这班，多看了两眼\\n"
    "粥勺磕在缸沿，响一声数一声\\n"
    "【预副歌】站台灯灭又亮\\n"
    "粥还温着，人还没来\\n"
    "【副歌】雾漫过山脊，我端着碗等天亮\\n"
    "锅盖响了三声，他说多添碗汤\\n"
    "汽笛穿过巷口，她还没回来\\n"
    "他把粥温着，像温着一句话\\n"
    "【主歌2】收摊时剩粥倒给流浪猫\\n"
    "猫不来，粥凉在桶里没人喝\\n"
    "早班车灯扫过，他背过身擦碗\\n"
    "街对过那盏灯，昨晚还亮着\\n"
    "保温杯搁在挡位旁，茶垢一圈圈\\n"
    "他数着日子，像数粥里的米粒\\n"
    "路灯下他蹲着，把粥碗摆正\\n"
    "【预副歌】天快亮，粥又热了一遍\\n"
    "那句话，他始终没问出口\\n"
    "【桥段】他说，明天还来，天总会亮的\\n"
    "抹布搭在缸沿，像个人还在等\\n"
    "那碗粥凉了又热，热了又凉\\n"
    "【副歌】雾漫过山脊，我端着碗等天亮\\n"
    "锅盖响了三声，他说多添碗汤\\n"
    "汽笛穿过巷口，她还没回来\\n"
    "他把粥温着，像温着一句话\\n"
    "【副歌】雾漫过山脊，我端着碗等天亮\\n"
    "锅盖响了三声，他说多添碗汤\\n"
    "汽笛穿过巷口，她还没回来\\n"
    "他把粥温着，像温着一句话"
)'''
assert old_clean in tsrc, "clean lyrics anchor not found"
tsrc = tsrc.replace(old_clean, new_clean, 1)
open(t, "w", encoding="utf-8").write(tsrc)
print("OK: _CLEAN_LYRICS expanded to full song")
