# -*- coding: utf-8 -*-
"""抓取多维度资料：经典分析 / 词人方法论 / 风格特征。"""
import re
import sys
from pathlib import Path

import httpx

sys.stdout.reconfigure(encoding="utf-8")

client = httpx.Client(timeout=25, trust_env=False, follow_redirects=True,
                      headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/151.0 Safari/537.36"})

TARGETS = [
    ("山丘歌词分析·李宗盛", "https://zhuanlan.zhihu.com/p/503910984", "08-lizongsheng-analysis.md"),
    ("林夕歌词创作技巧", "https://www.163.com/dy/article/EINDSAB7054285K9.html", "09-linxi-techniques.md"),
    ("聊聊古风音乐风格", "https://zhuanlan.zhihu.com/p/20794825", "10-guofeng-style.md"),
    ("李宗盛五十岁的山丘", "https://culture.ifeng.com/insight/special/shanqiu/", "11-shanqiu-story.md"),
]


def clean(html: str) -> str:
    t = re.sub(r"<script[\s\S]*?</script>", " ", html, flags=re.I)
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
                 ("&#39;", "'"), ("&ldquo;", "“"), ("&rdquo;", "”"), ("&hellip;", "…"),
                 ("&mdash;", "—"), ("&rsquo;", "'"), ("&lsquo;", "‘"), ("&#xff08;", "（"),
                 ("&#xff09;", "）"), ("&#xff0c;", "，"), ("&#xff1a;", "："), ("&#x3d;", "=")]:
        t = t.replace(a, b)
    t = re.sub(r"[ \t]+", " ", re.sub(r"\n{3,}", "\n\n", t)).strip()
    lines = []
    for ln in t.split("\n"):
        s = ln.strip()
        if not s:
            continue
        cn = len(re.findall(r"[\u4e00-\u9fff]", s))
        if cn < 2 and len(s) > 3:
            continue
        lines.append(s)
    return "\n".join(lines)


for name, url, fname in TARGETS:
    try:
        r = client.get(url)
        if r.status_code != 200:
            print(f"FAIL {name}: status {r.status_code}")
            continue
        t = clean(r.text)
        if len(t) < 400:
            print(f"SKIP {name}: too short {len(t)}")
            continue
        out = Path("D:/software/code/ideas/list/aigc-studio/knowledge/music") / fname
        out.write_text(f"# {name}\n\n> 来源：{url}\n\n" + t, encoding="utf-8")
        print(f"OK {fname}: {len(t)} chars")
    except Exception as exc:
        print(f"FAIL {name}: {type(exc).__name__} {str(exc)[:80]}")
