# -*- coding: utf-8 -*-
"""抓取词曲专业资料（网页 → 正文），供入库。"""
import re
import sys

import httpx

sys.stdout.reconfigure(encoding="utf-8")

URLS = {
    "编曲配器基础·层次空间情绪推进": "https://zsc.github.io/suno_tutorial/html/chapter9.html",
    "作词教室·豆瓣": "https://www.douban.com/group/topic/46028197/",
    "看完学会写歌·audioapp": "https://www.audioapp.cn/thread-43978-1-35146.html",
}

client = httpx.Client(timeout=25, trust_env=False, follow_redirects=True,
                      headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/151.0 Safari/537.36"})


def html_to_text(html: str) -> str:
    t = re.sub(r"<script[\s\S]*?</script>", " ", html, flags=re.I)
    t = re.sub(r"<style[\s\S]*?</style>", " ", t, flags=re.I)
    m = re.search(r"<(?:article|main)[\s\S]*?</(?:article|main)>", t, flags=re.I)
    if m:
        t = m.group(0)
    t = re.sub(r"</(?:p|div|h[1-6]|li|tr|td|section|blockquote|pre)>", "\n", t, flags=re.I)
    t = re.sub(r"<br\s*/?>", "\n", t, flags=re.I)
    t = re.sub(r"<[^>]+>", "", t)
    t = t.replace("&nbsp;", " ").replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    t = t.replace("&quot;", '"').replace("&#39;", "'").replace("&ldquo;", "“").replace("&rdquo;", "”")
    return re.sub(r"[ \t]+", " ", re.sub(r"\n{3,}", "\n\n", t)).strip()


for name, url in URLS.items():
    try:
        r = client.get(url)
        text = html_to_text(r.text)
        print(f"===== {name} | status={r.status_code} | len={len(text)}")
        print(text[:3000])
        print()
    except Exception as exc:
        print(f"===== {name} | FAIL: {type(exc).__name__} {str(exc)[:120]}")
        print()
