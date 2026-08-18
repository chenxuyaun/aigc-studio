# -*- coding: utf-8 -*-
"""完整抓取 suno 编曲教程第 9 章，保存为 markdown 入库。"""
import re
import sys
from pathlib import Path

import httpx

sys.stdout.reconfigure(encoding="utf-8")

url = "https://zsc.github.io/suno_tutorial/html/chapter9.html"
client = httpx.Client(timeout=25, trust_env=False, follow_redirects=True,
                      headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/151.0 Safari/537.36"})
r = client.get(url)
t = re.sub(r"<script[\s\S]*?</script>", " ", r.text, flags=re.I)
t = re.sub(r"<style[\s\S]*?</style>", " ", t, flags=re.I)
m = re.search(r"<(?:article|main)[\s\S]*?</(?:article|main)>", t, flags=re.I)
if m:
    t = m.group(0)
# 表格行保留
t = re.sub(r"</tr>", "\n", t, flags=re.I)
t = re.sub(r"</t[dh]>", " | ", t, flags=re.I)
t = re.sub(r"</(?:p|div|h[1-6]|li|tr|td|section|blockquote|pre)>", "\n", t, flags=re.I)
t = re.sub(r"<br\s*/?>", "\n", t, flags=re.I)
t = re.sub(r"<[^>]+>", "", t)
for a, b in [("&nbsp;", " "), ("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">"), ("&quot;", '"'),
             ("&#39;", "'"), ("&ldquo;", "“"), ("&rdquo;", "”"), ("&hellip;", "…")]:
    t = t.replace(a, b)
t = re.sub(r"[ \t]+", " ", re.sub(r"\n{3,}", "\n\n", t)).strip()

out = Path("D:/software/code/ideas/list/aigc-studio/knowledge/music/02-arrangement-fundamentals.md")
out.write_text("# 编曲与配器基础（层次、空间、情绪推进）\n\n> 来源：Suno 教程第 9 章（zsc.github.io/suno_tutorial）\n\n" + t, encoding="utf-8")
print(f"saved: {out} ({len(t)} chars)")
