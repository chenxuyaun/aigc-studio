# ruff: noqa: T201 E501
"""《双城交换杀人》修订：按读者点评植入精确时间表 + 交叉验证证据 + 废线索回收。

权威修订数据（主编设计）：
- 时间表：陈启明死于 5/12 02:13（发现 08:40），魏延之于 5/13 04:57（发现 21:30）——相隔 25 小时，
  手抄本邮戳 5/11（案发前一日寄出）——「同时发生」是叙述伪造。
- 动机闭环：贺青是 Z 城矿难遇难矿工之子（改名换姓）；陈、魏当年合谋私吞赔偿金。
  先杀陈（序幕+诱饵），再用交换杀人假象掩护真正的目标魏延之。
- 交叉证据：① 魏的心脏起搏器节律（Z 城矿工医院植入）② 两案凶器同为 Z 城器械库手术钢
  ③ 手抄本纸张与 Z 城病历纸同批号 ④ 假急诊单笔迹 = 贺青记账本笔迹
- 废线索回收：白鷉磁带背景音（5/12 夜 B 城渡轮汽笛+医院广播）暴露时间线；旧器械 = 凶器来源。
"""

import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

import httpx

BASE = "http://localhost:8002/api/v1"
MODEL = "gpt-oss-120b-medium"
PID = "c49679e9-1d19-4638-bac5-f20640364466"
ENV_PATH = Path(r"D:\software\code\ideas\list\aigc-studio\.env")
OUT_DIR = Path(r"D:\software\code\ideas\list\aigc-studio")
PASSED: list[str] = []
FAILED: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    (PASSED if cond else FAILED).append(name)
    print(("PASS" if cond else "FAIL"), name, detail[:150] if detail else "")


def env(k: str) -> str:
    with open(ENV_PATH, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line.startswith(k + "="):
                return line.split("=", 1)[1].strip()
    raise KeyError(k)


def main() -> None:
    user, pwd = env("INITIAL_ADMIN_USERNAME"), env("INITIAL_ADMIN_PASSWORD")
    c = httpx.Client(timeout=600, base_url=BASE)
    token = c.post("/auth/login", json={"username": user, "password": pwd}).json()["access_token"]
    h = {"Authorization": f"Bearer {token}"}

    # 章节 ID 映射
    chs = c.get(f"/story/projects/{PID}/chapters", headers=h).json().get("items", [])
    by_no = {ch["chapter_no"]: ch for ch in chs}

    # 权威修订数据（统一注入，保证一致性）
    TIMELINE = (
        "【案件时间表·权威数据】\n"
        "· A 城陈启明：死于 5 月 12 日凌晨 02:13（法医推定），08:40 被钟点工发现，"
        "公寓电梯监控显示 02:00 有人上行、02:20 下行，画面中的人裹着医院常见的旧式灰大衣。\n"
        "· B 城魏延之：死于 5 月 13 日凌晨 04:57（法医推定），当日 21:30 被夜班护士发现于更衣间，"
        "排班表显示他案发当夜本应急诊手术，却因一张『区急救中心借调』的假急诊单被调离。\n"
        "· 两案实际相隔 25 小时——『同日发现、同步发生』是叙述层面的伪造。\n"
        "· 交换杀人手抄本邮戳：5 月 11 日（两案之前）——凶手提前寄出，证明其预谋。\n"
        "· 白鷉磁带的背景音：5 月 12 日 22:40 的 B 城渡轮汽笛与『东岸医院夜间广播』——"
        "录音当晚，作者身在 B 城；而手抄本此时已寄抵 A 城。磁带不是坦白，是时间线证物。\n"
        "· 动机：贺青实为 Z 城矿难遇难矿工之子（当年改名换姓），陈启明（会计）与魏延之（院方代表）"
        "当年合谋伪造矿难赔偿账目、私吞抚恤金。贺青先杀陈启明——那是复仇的序幕，也是诱饵；"
        "再用『交换杀人』的假象布局，让魏延之的死成为『两个无动机凶手之一』——第二案才是他的真正目标。\n"
        "· 交叉验证证据：① 魏延之院内心电图带起搏器节律——他体内有 Z 城矿工医院 5 年前植入的心脏起搏器，"
        "与陈启明锁骨钢钉同一位主刀医生；② 两案凶器均为同批次手术钢（Z 城矿工医院器械库旧器械——"
        "周羡收藏的那批）；③ 手抄本纸张水印批号与 Z 城矿工医院病历纸同批（XC-114）；"
        "④ 假急诊单笔迹与贺青旧书铺记账本笔迹鉴定吻合。"
    )

    # 逐章修订指令
    instructions = {
        1: (
            "修订本章：植入精确时间戳与『同日发现』的叙述陷阱。\n"
            "1. 开篇的案发通告改为精确时间格式：A 城陈启明 5 月 12 日 02:13 死亡、08:40 发现；"
            "B 城魏延之 5 月 13 日 04:57 死亡、21:30 发现——两案『几乎同时被宣布』的戏剧性来自警方简报的同桌展示，"
            "但死亡时间必须明写为两个不同的凌晨，让细心读者第一次感到时间对不上。\n"
            "2. 加入电梯监控灰大衣、手抄本邮戳日期（5 月 11 日）等细节描写。\n"
            "3. 白鷉的磁带首次出现时，描写磁带标签上的日期与倒带长度，但不要解释。\n"
            "4. 保持章节原有叙事框架与人名，只做上述植入与衔接。\n" + TIMELINE
        ),
        4: (
            "修订本章（死亡时间线）：把『猜测』升级为『交叉验证』。\n"
            "1. 秦澜与周羡的对话加入硬证据：魏延之的院内心电图带起搏器节律——"
            "他在 Z 城矿工医院 5 年前植入过心脏起搏器；周羡查旧档案发现陈启明的锁骨钢钉"
            "与魏的起搏器是同一主刀医生、同一批手术。\n"
            "2. 手抄本纸张水印批号 XC-114 与 Z 城矿工医院病历纸同批——纸张化验报告出现。\n"
            "3. 两案凶器刀痕送检：同批次手术钢（Z 城器械库旧器械）——周羡『收藏的那批旧器械』"
            "在此回收：他终于认出凶器来自自己熟悉的器械库。\n"
            "4. 时间线对比表格化：两案死亡时间并排，秦澜指着 25 小时的间隔说出『如果是交换杀人，"
            "他们为什么不等在同一天？』\n" + TIMELINE
        ),
        8: (
            "修订本章（交换杀手）：真相揭示必须带完整证据链，不能再是口号。\n"
            "1. 白鷉磁带的第二次检验：背景音里的 B 城渡轮汽笛与东岸医院夜间广播，"
            "时间戳锁定 5 月 12 日 22:40——录音当晚人在 B 城，而手抄本 5 月 11 日已寄抵 A 城。"
            "磁带不是坦白，是时间线证物：『交换杀人』的规则是叙述的伪造。\n"
            "2. 贺青的动机完整化：他不是守密者，是 Z 城矿难遇难矿工之子；陈启明（会计）与魏延之"
            "（院方代表）当年合谋私吞抚恤金。先杀陈是复仇序幕+诱饵，杀魏才是真正目标——"
            "用交换杀人假象让魏的死找不到凶手。\n"
            "3. 笔迹鉴定：假急诊单与贺青记账本吻合——他伪造了调离魏延之的急诊单。\n"
            "4. 贺青的心理转折要有内心独白：从『只想讨回公道』到『把自己也编进交换杀人的规则里』。\n"
            + TIMELINE
        ),
        9: (
            "修订本章（旧书铺对质·终章）：收束必须用证据链裁决，并给出时间表复盘。\n"
            "1. 对质的高潮改为『证据链依次落地』：电梯监控灰大衣→起搏器/钢钉同源→纸张批号→"
            "笔迹鉴定→磁带背景音时间戳——每一项都指向同一个结论：两案相隔 25 小时，"
            "『交换杀人』是贺青的叙述装置。\n"
            "2. 加入时间表复盘段落：把 5/11 邮戳、5/12 02:13、5/12 22:40、5/13 04:57 四个时间点"
            "钉在同一张纸上，读者/角色同步完成推理。\n"
            "3. 白鷉的最后一封信收尾：承认自己是贺青安排的『回声』，信里只有一句话："
            "『规则是假的，但债是真的。』\n"
            "4. 贺青被捕时的平静描写：他终于说出真名。\n" + TIMELINE
        ),
    }

    for no, inst in sorted(instructions.items()):
        ch = by_no.get(no)
        if ch is None:
            check(f"第{no}章修订", False, "章节不存在")
            continue
        url = f"/story/chapters/{ch['id']}/revise?instruction={urllib.parse.quote(inst)}&model={MODEL}"
        r = c.post(url, headers=h, timeout=600)
        if r.status_code == 200:
            body = r.json()
            check(f"第{no}章修订《{ch['title']}》", True, f"{body.get('word_count')} 字")
        else:
            check(f"第{no}章修订《{ch['title']}》", False, r.text[:150])
        time.sleep(2)

    # 重新导出
    r = c.get(f"/story/projects/{PID}/export", headers=h, params={"format": "markdown"})
    if r.status_code == 200:
        (OUT_DIR / "双城交换杀人.md").write_text(r.text, encoding="utf-8")
        total = sum(
            ch.get("word_count") or 0
            for ch in c.get(f"/story/projects/{PID}/chapters", headers=h).json().get("items", [])
        )
        check("导出 markdown", True, f"全书 {total} 字")
    else:
        check("导出 markdown", False, r.text[:120])
    r = c.get(f"/story/projects/{PID}/export", headers=h, params={"format": "epub"})
    if r.status_code == 200:
        (OUT_DIR / "双城交换杀人.epub").write_bytes(r.content)
        check("导出 epub", True, f"{len(r.content)} bytes")
    else:
        check("导出 epub", False, r.text[:120])

    print(f"\n== {len(PASSED)} passed, {len(FAILED)} failed ==")
    sys.exit(1 if FAILED else 0)


if __name__ == "__main__":
    main()
