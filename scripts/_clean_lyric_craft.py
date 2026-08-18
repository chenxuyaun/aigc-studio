# -*- coding: utf-8 -*-
"""清理 03-lyric-craft.md：去论坛噪音与乱码字符，保留实质内容。"""
import re

p = "D:/software/code/ideas/list/aigc-studio/knowledge/music/03-lyric-craft.md"
t = open(p, encoding="utf-8").read()

# 去掉论坛加密乱码（保留中文/英文/数字/常见标点）
t = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", t)
# 论坛伪随机字符（如 "& @6 u5 D+ k3" / "* T# h2 D*4" 模式）——去掉行内散落的杂字符
t = re.sub(r"[#@%^&*+~`_|\\/]{2,}", " ", t)

lines = []
skip_prefixes = (
    "登录", "注册", "首页", "音频论坛", "音频硬件", "声卡", "电脑软件", "免费插件",
    "乐器发布", "合成器", "二手音频", "产品展示", "关于我们", "自动登录", "找回密码",
    "快速注册", "快捷导航", "没有账号", "帖子", "道具", "勋章", "收藏", "任务",
    "设置", "我的收藏", "退出", "全部", "搜索", "发帖", "请 登录",
)
for ln in t.split("\n"):
    s = ln.strip()
    if not s:
        continue
    if s in skip_prefixes or s.startswith("&rsaquo;") or s.startswith("&") or s.startswith("回复"):
        continue
    # 论坛时间戳/用户行
    if re.match(r"^\d+#$|^jd-|^\d{4}-\d{1,2}-\d{1,2} \d", s):
        continue
    lines.append(s)

clean = "\n".join(lines)
clean = re.sub(r"\n{3,}", "\n\n", clean)
open(p, "w", encoding="utf-8").write(clean)
print(f"cleaned: {len(clean)} chars, {len(lines)} lines")
print(clean[:600])
print("...")
print(clean[-600:])
