# -*- coding: utf-8 -*-
"""临时脚本：统一修复 Field render-prop / MarkdownContent content / ErrorState error。"""
import io
import re

FILES = [
    "src/pages/storystudio/ChapterEditor.tsx",
    "src/pages/storystudio/ChapterList.tsx",
    "src/pages/storystudio/CrewPanel.tsx",
    "src/pages/storystudio/WorldPanel.tsx",
    "src/pages/storystudio/SerialPanel.tsx",
    "src/pages/StoryStudioPage.tsx",
    "src/pages/StoryProjectPage.tsx",
]


def fix_field_input(s: str) -> str:
    """<Field label="X">\n <input .../>\n </Field> → render-prop 形式。"""
    # 单行 input
    pat = re.compile(
        r'<Field label="([^"]*)">\s*\n?\s*<input([^>]*?)/>\s*\n?\s*</Field>'
    )
    s2 = pat.sub(
        lambda m: (
            '<Field label="%s">\n'
            "        {({ id, describedBy }) => (\n"
            "          <input\n"
            "            id={id}\n"
            "            aria-describedby={describedBy}\n"
            "            %s\n"
            "          />\n"
            "        )}\n"
            "      </Field>"
        )
        % (m.group(1), m.group(2)),
        s,
    )
    return s2


def fix_field_textarea(s: str) -> str:
    pat = re.compile(
        r'<Field label="([^"]*)">\s*\n?\s*<Textarea([^>]*?)rows=\{(\d+)\}([^>]*?)/>\s*\n?\s*</Field>'
    )
    s2 = pat.sub(
        lambda m: (
            '<Field label="%s">\n'
            "        {({ id, describedBy }) => (\n"
            "          <Textarea\n"
            "            id={id}\n"
            "            aria-describedby={describedBy}\n"
            "            rows={%s}%s\n"
            "          />\n"
            "        )}\n"
            "      </Field>"
        )
        % (m.group(1), m.group(3), m.group(4)),
        s,
    )
    # 无 rows 的 Textarea（StoryStudioPage 梗概）
    pat2 = re.compile(
        r'<Field label="([^"]*)">\s*\n?\s*<Textarea([^>]*?)rows=\{(\d+)\}\s*\n?\s*(value=\{[^}]*\}\s*\n?\s*onChange=\{[^}]*\})/>\s*\n?\s*</Field>'
    )
    s2 = pat2.sub(
        lambda m: (
            '<Field label="%s">\n'
            "        {({ id, describedBy }) => (\n"
            "          <Textarea\n"
            "            id={id}\n"
            "            aria-describedby={describedBy}\n"
            "            rows={%s}\n"
            "            %s\n"
            "          />\n"
            "        )}\n"
            "      </Field>"
        )
        % (m.group(1), m.group(3), m.group(4)),
        s2,
    )
    return s2


def fix_textarea_field(s: str) -> str:
    """value/onChange 跨行 + rows 在前的情况。"""
    pat = re.compile(
        r'<Field label="([^"]*)">\s*\n?\s*<Textarea\n(\s*)rows=\{(\d+)\}\n(\s*)value=\{(.*?)\}\n(\s*)onChange=\{(.*?)\}\s*\n?/>\s*\n?\s*</Field>',
        re.S,
    )
    s2 = pat.sub(
        lambda m: (
            '<Field label="%s">\n'
            "        {({ id, describedBy }) => (\n"
            "          <Textarea\n"
            "            id={id}\n"
            "            aria-describedby={describedBy}\n"
            "            rows={%s}\n"
            "            value={%s}\n"
            "            onChange={%s}\n"
            "          />\n"
            "        )}\n"
            "      </Field>"
        )
        % (m.group(1), m.group(3), m.group(5), m.group(7)),
        s2,
    )
    return s2


for f in FILES:
    path = f
    s = io.open(path, encoding="utf-8").read()
    before = s
    s = fix_field_input(s)
    s = fix_field_textarea(s)
    s = fix_textarea_field(s)
    if s != before:
        io.open(path, "w", encoding="utf-8").write(s)
        print("field-fixed", f)

# MarkdownContent children → content
p = "src/pages/storystudio/ChapterEditor.tsx"
s = io.open(p, encoding="utf-8").read()
s = s.replace(
    '<MarkdownContent>{display || "（空）"}</MarkdownContent>',
    '<MarkdownContent content={display || "（空）"} />',
)
io.open(p, "w", encoding="utf-8").write(s)
print("markdown-fixed")

# ErrorState message → error
p = "src/pages/StoryStudioPage.tsx"
s = io.open(p, encoding="utf-8").read()
s = s.replace("<ErrorState message={error} onRetry={() => void load()} />", "<ErrorState error={error} onRetry={() => void load()} />")
io.open(p, "w", encoding="utf-8").write(s)
print("errorstate-fixed")

p = "src/pages/StoryProjectPage.tsx"
s = io.open(p, encoding="utf-8").read()
s = s.replace("<ErrorState message={error} onRetry={() => void load()} />", "<ErrorState error={error} onRetry={() => void load()} />")
io.open(p, "w", encoding="utf-8").write(s)
print("errorstate2-fixed")
