# -*- coding: utf-8 -*-
"""清理 knowledge/music/*.md 中的 HTML 标签残留。"""
import re
from pathlib import Path

kb = Path("D:/software/code/ideas/list/aigc-studio/knowledge/music")
for f in kb.glob("*.md"):
    t = f.read_text(encoding="utf-8")
    if "<" not in t and "&" not in t:
        continue
    t = re.sub(r"<p[^>]*>", "", t)
    t = re.sub(r"</p>", "\n", t)
    t = re.sub(r"<[^>]+>", "", t)
    t = t.replace("&#xff08;", "（").replace("&#xff09;", "）").replace("&#xff0c;", "，")
    t = t.replace("&#x3d;", "=").replace("&#xff1a;", "：").replace("&#xff1b;", "；")
    t = re.sub(r"\n{3,}", "\n\n", t).strip()
    f.write_text(t, encoding="utf-8")
    print(f"cleaned: {f.name} ({len(t)} chars)")
