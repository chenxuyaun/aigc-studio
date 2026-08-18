# -*- coding: utf-8 -*-
"""抓取 Kimi WebBridge 产品页的扩展商店链接。"""
import httpx
import re
import sys

sys.stdout.reconfigure(encoding="utf-8")
client = httpx.Client(timeout=30, trust_env=False, follow_redirects=True)
r = client.get("https://www.kimi.com/zh-cn/products/kimi-webbridge")
print("status:", r.status_code)
text = re.sub(r"<script.*?</script>", "", r.text, flags=re.S)
text = re.sub(r"<style.*?</style>", "", text, flags=re.S)
links = re.findall(r"https?://[^\"'\\\s<>]+", text)
seen = set()
for l in links:
    low = l.lower()
    if ("chromewebstore" in low or "microsoftedge" in low or "crx" in low
            or "extension" in low or "download" in low or "安装" in l):
        if l not in seen:
            seen.add(l)
            print("LINK:", l[:160])
