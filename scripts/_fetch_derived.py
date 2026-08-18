# -*- coding: utf-8 -*-
"""抓取衍生资料：和弦进行 / 十三辙 / 韵脚 / 中国风押韵。"""
import re
import sys
from pathlib import Path

import httpx

sys.stdout.reconfigure(encoding="utf-8")

client = httpx.Client(timeout=25, trust_env=False, follow_redirects=True,
                      headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/151.0 Safari/537.36"})

TARGETS = [
    ("4536251和常见和弦走向·乐理", "https://blog.csdn.net/lpw_cn/article/details/108145202", "04-chord-progressions.md"),
    ("韵律十三辙·中文押韵体系", "https://www.meipian.cn/45uvcv24", "05-thirteen-rhyme.md"),
    ("歌词创作的韵脚·音频应用", "https://www.audioapp.cn/forum.php?action=printable&mod=viewthread&tid=54965", "06-rhyme-feet.md"),
    ("中国风歌词押韵", "https://bbs.zgycgc.com/forum.php?mod=viewthread&tid=62516", "07-chinese-style-rhyme.md"),
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
                 ("&mdash;", "—"), ("&rsquo;", "'"), ("&lsquo;", "‘")]:
        t = t.replace(a, b)
    t = re.sub(r"[ \t]+", " ", re.sub(r"\n{3,}", "\n\n", t)).strip()
    # 去纯噪音行（无中文的短行）
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
