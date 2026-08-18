# -*- coding: utf-8 -*-
"""抓作词与和声资料。"""
import re
import sys
from pathlib import Path

import httpx

sys.stdout.reconfigure(encoding="utf-8")

client = httpx.Client(timeout=25, trust_env=False, follow_redirects=True,
                      headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/151.0 Safari/537.36"})


def save(name: str, url: str, out_name: str) -> None:
    try:
        r = client.get(url)
        if r.status_code != 200:
            print(f"{name}: status {r.status_code}")
            return
        t = re.sub(r"<script[\s\S]*?</script>", " ", r.text, flags=re.I)
        t = re.sub(r"<style[\s\S]*?</style>", " ", t, flags=re.I)
        m = re.search(r"<(?:article|main)[\s\S]*?</(?:article|main)>", t, flags=re.I)
        if m:
            t = m.group(0)
        t = re.sub(r"</tr>", "\n", t, flags=re.I)
        t = re.sub(r"</t[dh]>", " | ", t, flags=re.I)
        t = re.sub(r"</(?:p|div|h[1-6]|li|tr|td|section|blockquote|pre)>", "\n", t, flags=re.I)
        t = re.sub(r"<br\s*/?>", "\n", t, flags=re.I)
        t = re.sub(r"<[^>]+>", "", t)
        for a, b in [("&nbsp;", " "), ("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">"), ("&quot;", '"'),
                     ("&#39;", "'"), ("&ldquo;", "“"), ("&rdquo;", "”"), ("&hellip;", "…")]:
            t = t.replace(a, b)
        t = re.sub(r"[ \t]+", " ", re.sub(r"\n{3,}", "\n\n", t)).strip()
        if len(t) < 300:
            print(f"{name}: too short ({len(t)})")
            return
        out = Path("D:/software/code/ideas/list/aigc-studio/knowledge/music") / out_name
        out.write_text(f"# {name}\n\n> 来源：{url}\n\n" + t, encoding="utf-8")
        print(f"OK {out_name}: {len(t)} chars")
    except Exception as exc:
        print(f"{name}: FAIL {type(exc).__name__} {str(exc)[:100]}")


save("作词教室·写作技巧合集", "https://www.audioapp.cn/thread-43978-1-35146.html", "03-lyric-craft.md")
save("写歌词的方法与技巧", "https://www.zhihu.com/question/55294800", "04-zhihu-lyrics.md")
