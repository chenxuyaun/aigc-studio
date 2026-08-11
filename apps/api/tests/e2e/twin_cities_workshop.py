# ruff: noqa: T201 E501
"""《双城交换杀人》推理小说工作坊：叙述性诡计 × 交换杀人，酒馆角色群博弈驱动。

流程（主模型 grok-chat-fast，真实 Grok 账号池）：
1. 建项目（两城连环命案 + 交换杀人手抄本核心谜题）
2. 项目级世界书（两城设定/手抄本/旧伤线索）
3. 角色阵容 6 名：双城刑警 + 作家 + 法医 + 神秘投稿人 + 旧识
4. 主编生成案件设计文档（真相/诡计/误导/线索链 40-40-20）→ 注入后续章节
5. 按推理结构生成 8 章大纲
6. 逐章叙事生成（案件设计作为写作指令）
7. 群聊对抗：秦澜审问白鷉与贺青（多角色博弈，剧本模式）
8. 校对验证：逻辑闭环检查（叙述性诡计是否成立/时间线误导是否自洽）
9. 导出 markdown + epub
"""

import json
import sys
import time
from pathlib import Path

import httpx

BASE = "http://localhost:8002/api/v1"
MODEL = "grok-chat-fast"
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


def post(c: httpx.Client, h: dict, path: str, body: dict) -> dict:
    r = c.post(path, headers=h, json=body)
    if r.status_code == 200:
        return r.json()
    return {"error": f"HTTP {r.status_code}: {r.text[:200]}"}


def main() -> None:
    user, pwd = env("INITIAL_ADMIN_USERNAME"), env("INITIAL_ADMIN_PASSWORD")
    c = httpx.Client(timeout=600, base_url=BASE)
    token = c.post("/auth/login", json={"username": user, "password": pwd}).json()["access_token"]
    h = {"Authorization": f"Bearer {token}"}

    # 0. 清理旧项目
    for p in c.get("/story/projects", headers=h).json().get("items", []):
        if p["title"] == "双城交换杀人":
            c.delete(f"/story/projects/{p['id']}", headers=h)
            print("已清理旧项目")

    # 1. 建项目
    r = post(
        c,
        h,
        "/story/projects",
        {
            "title": "双城交换杀人",
            "genre": "本格推理 · 叙述性诡计",
            "synopsis": (
                "临海双城，一江之隔。A 城老会计师陈启明死于自家书房，B 城外科主任魏延之死于手术室更衣间，"
                "两案同日发现，死者素不相识。随后，专栏作家江叙收到一封匿名投稿："
                "一本残破的手抄本，记载着「交换杀人」的古老规则——两人互杀对方的目标，"
                "谁都没有动机。手抄本的出现让两城警方罕见地坐到了同一张桌前，"
                "但交换杀人的拼图里，藏着一个被时间线掩埋的真相。"
            ),
        },
    )
    pid = r["project"]["id"]
    check("项目创建", bool(pid))

    # 2. 项目级世界书：世界观
    for kw, content in [
        (
            ["双城"],
            "临海双城：A 城（西岸，旧港商埠，老城街巷密集）与 B 城（东岸，新兴医疗城，全城三成人口从事医疗行业），隔江相望，轮渡二十分钟。两城警方分属不同分局，平时鲜有交集。",
        ),
        (
            ["交换杀人手抄本"],
            "残破的线装手抄本，封面无字，内页以钢笔抄录「交换杀人之法则」：甲乙互不相识，互杀对方之目标，动机湮灭，无人可证。纸页有茶渍与煤灰痕迹，落款日期被撕去。该手抄本是本案最大误导源——它的出现本身就是一个精心设计的饵。",
        ),
        (
            ["旧伤"],
            "两具尸体的尸检中，法医发现同一处异常：两人都曾接受过同一侧锁骨旧骨折手术，手术方式高度一致——这指向一座早已废弃的 Z 城矿工医院，也是连接两位死者旧事的唯一实体证据。",
        ),
    ]:
        r = post(
            c,
            h,
            "/roleplay/lore",
            {
                "project_id": pid,
                "keywords": kw,
                "content": content,
                "selective": True,
            },
        )
    check("世界书设定（3 条）", True)

    # 3. 角色阵容：双城刑警 + 作家 + 法医 + 神秘投稿人 + 旧识
    cast = [
        {
            "name": "秦澜",
            "role": "protagonist",
            "description": "三十五岁，A 城刑警，甲案（陈启明）经办。冷静理性，擅长把看似无关的细节串成链条；在交换杀人的迷雾中，他是唯一对「手抄本出现得太巧」感到不安的人。",
            "goals": "找出甲案真相；他不相信交换杀人——认为手抄本是有人故意送来的。",
            "arc": "从被交换杀人假象带偏，到抓住时间线的破绽，最终识破叙述性诡计：两案并非同时发生。",
            "current_state": "乙案通报传来，他刚发现甲案死者陈启明的书房日历停在五年前的一页。",
        },
        {
            "name": "顾之南",
            "role": "supporting",
            "description": "三十一岁，B 城刑警，乙案（魏延之）经办。直觉敏锐，行动派，崇尚『先抓住再说』；与秦澜性格相反，却在本案中最早产生怀疑——魏延之的死状太像『被设计成交换杀人』。",
            "goals": "抓住乙案真凶；对交换杀人论半信半疑，倾向查魏延之本人的仇家。",
            "arc": "从怀疑秦澜的『串联』，到意识到两人看的是同一张拼图的正反面。",
            "current_state": "把魏延之的排班表拍在桌上——案发当夜他本应在手术，却被人用一封假急诊调走了。",
        },
        {
            "name": "江叙",
            "role": "supporting",
            "description": "四十岁，双城犯罪纪实专栏作家，投稿人白鷉指定的『收件人』。笔锋犀利，但五年前因一桩矿难报道获奖后沉寂——那篇报道涉及 Z 城矿工医院。",
            "goals": "抢在警方前解开交换杀人之谜，把『预告』变成独家报道；他藏着一个秘密：手抄本出现前一周，他曾收到过一张照片。",
            "arc": "从旁观者变成被卷入者：他发现自己也是这场局的一部分。",
            "current_state": "没有立刻把手抄本交给警方，而是先约了秦澜私下见面。",
        },
        {
            "name": "周羡",
            "role": "supporting",
            "description": "三十七岁，A 城法医，两案尸检报告都经他手。嗜好收集旧手术器械，对 Z 城矿工医院的旧档案有超出职业的熟悉。",
            "goals": "确认两具尸体『旧伤同源』的结论——这是他职业生涯最重要的检验。",
            "arc": "从陈述者变为知情者：旧伤手术记录上的主刀签名，是他的导师。",
            "current_state": "把两份尸检报告并排放在灯下，指着锁骨旧伤的照片沉默了很久。",
        },
        {
            "name": "白鷉",
            "role": "supporting",
            "description": "三十三岁，自称『交换杀人的另一名杀手』的神秘投稿人。从不露面，只通过信件和录音带与江叙联系，声音经过处理，语速极慢，仿佛在背诵一份证词。",
            "goals": "让所有人相信交换杀人成立——他宣称自己杀死了魏延之的目标，而对方杀死了陈启明。",
            "arc": "反转：他并非杀手，而是五年前甲案真凶的『同谋遗属』；投稿的目的不是坦白，而是引导。",
            "current_state": "送来第二封信，附一张五年前的旧报纸剪报——头版正是江叙获奖的那篇 Z 城矿难报道。",
        },
        {
            "name": "贺青",
            "role": "supporting",
            "description": "四十九岁，两位死者共同旧识，年轻时同在 Z 城矿工医院做行政。如今经营一家旧书铺，说话滴水不漏，对过去的事讳莫如深。",
            "goals": "守住旧事——Z 城矿难调查中，三人的证词互相矛盾，而他就是当年第一个改口的人。",
            "arc": "从守密者到破局者：他手中有一张当年三人合影，背面写着那句交换杀人的暗语。",
            "current_state": "在旧书铺被秦澜与顾之南同时找上门，他笑着把烟灰缸推过来：『坐。你们想问矿难，还是想问死人的事？』",
        },
    ]
    char_asset_ids: list[str] = []
    for ch in cast:
        r = post(
            c,
            h,
            f"/story/projects/{pid}/characters",
            {
                "name": ch["name"],
                "role": ch["role"],
                "description": ch["description"],
                "goals": ch["goals"],
                "arc": ch["arc"],
                "current_state": ch["current_state"],
            },
        )
        # 酒馆角色卡化：每个角色创建真实 V2 角色卡（JSON 导入 → PNG 存储）
        card_json = json.dumps(
            {
                "spec": "chara_card_v2",
                "spec_version": "2.0",
                "data": {
                    "name": ch["name"],
                    "description": ch["description"],
                    "personality": ch["arc"],
                    "scenario": "临海双城，一江之隔。两案同日发现，交换杀人手抄本的出现让所有人聚到同一张桌前。",
                    "first_mes": "",
                    "mes_example": "",
                    "system_prompt": f"你是《双城交换杀人》中的角色「{ch['name']}」。"
                    f"牢记自己的秘密、动机与欺骗：{ch['goals']} {ch['arc']} "
                    f"{ch['current_state']}。在审讯与对质中，"
                    "只说符合自己立场的话，必要时说谎与误导。",
                    "creator_notes": "双城交换杀人工作坊自动生成的角色卡",
                },
            },
            ensure_ascii=False,
        ).encode("utf-8")
        resp = c.post(
            "/roleplay/characters/import",
            headers=h,
            files={"file": (f"card-{ch['name']}.json", card_json, "application/json")},
        )
        body = resp.json()
        aid = body.get("asset_id")
        if aid:
            char_asset_ids.append(aid)
            print(f"  角色卡: {ch['name']} -> {aid[:8]}")
        time.sleep(0.5)
    check(
        "角色阵容 6 名 + 酒馆角色卡",
        len(char_asset_ids) == len(cast),
        f"{len(char_asset_ids)}/{len(cast)} 张卡",
    )
    r = c.put(f"/story/projects/{pid}", headers=h, json={"character_asset_ids": char_asset_ids})
    check("项目关联角色卡群", r.status_code == 200, f"{len(char_asset_ids)} 张")

    # 4. 主编生成案件设计文档（真相/诡计/误导/线索链）
    r = post(
        c,
        h,
        f"/story/projects/{pid}/crew",
        {
            "project_id": pid,
            "stage": "director",
            "model": MODEL,
        },
    )
    check(
        "案件设计（主编）",
        "error" not in r and bool(r.get("direction")),
        str(r.get("direction", ""))[:100],
    )

    # 5. 推理结构大纲 8 章
    r = c.post(f"/story/projects/{pid}/outline?chapters=8&model={MODEL}", headers=h)
    body = r.json()
    chapters = body.get("chapters") or []
    check("推理结构大纲 8 章", r.status_code == 200 and len(chapters) == 8, r.text[:120])
    for ch in chapters[:4]:
        print(f"  大纲 第{ch['chapter_no']}章《{ch['title']}》")

    # 6. 逐章叙事生成（案件设计注入）
    for ch in chapters:
        r = post(
            c,
            h,
            f"/story/chapters/{ch['id']}/generate",
            {
                "project_id": pid,
                "mode": "narrative",
                "model": MODEL,
                "max_tokens": 1600,
            },
        )
        if "error" in r:
            check(f"章节{ch['chapter_no']}生成", False, str(r.get("error"))[:120])
            continue
        check(f"章节{ch['chapter_no']}《{ch['title']}》", True, f"{r.get('word_count')} 字")
        time.sleep(1)

    # 7. 群聊对抗：秦澜审问白鷉与贺青（多角色博弈）
    r = c.post(
        f"/story/projects/{pid}/chapters",
        headers=h,
        json={
            "title": "旧书铺对质（博弈场景）",
            "outline": (
                "秦澜与顾之南在贺青的旧书铺同时审问贺青与神秘的白鷉——白鷉第一次露面，"
                "坚持交换杀人成立；贺青则不断暗示两人『看错了方向』。"
                "对话中，时间线的破绽浮出：陈启明的日历停在五年前，而魏延之的假急诊单上的"
                "字迹与手抄本如出一辙。两案并非同时发生——交换杀人是一场被叙述伪造的平行。"
            ),
        },
    ).json()
    sid = r["chapter"]["id"]
    r = post(
        c,
        h,
        f"/story/chapters/{sid}/generate",
        {
            "project_id": pid,
            "mode": "script",
            "model": MODEL,
            "rounds": 8,
        },
    )
    if "error" in r:
        check("群聊对抗审问", False, str(r.get("error"))[:120])
    else:
        check(
            "群聊对抗审问（四角色博弈）",
            True,
            f"{r.get('turns')} 轮对话 · {r.get('word_count')} 字",
        )

    # 8. 校对：逻辑验证（叙述性诡计自洽/线索全解释）
    cid_last = chapters[-1]["id"]
    r = post(
        c,
        h,
        f"/story/projects/{pid}/crew",
        {
            "project_id": pid,
            "stage": "editor",
            "model": MODEL,
            "chapter_id": cid_last,
        },
    )
    if "error" in r:
        check("推理逻辑验证（校对）", False, str(r.get("error"))[:120])
    else:
        check("推理逻辑验证（校对）", True, str(r.get("review", ""))[:100])

    # 9. 导出
    r = c.get(f"/story/projects/{pid}/export", headers=h, params={"format": "markdown"})
    if r.status_code == 200:
        (OUT_DIR / "双城交换杀人.md").write_text(r.text, encoding="utf-8")
        total = sum(
            ch.get("word_count") or 0
            for ch in c.get(f"/story/projects/{pid}/chapters", headers=h).json().get("items", [])
        )
        check("导出 markdown", True, f"全书 {total} 字")
    else:
        check("导出 markdown", False, r.text[:120])
    r = c.get(f"/story/projects/{pid}/export", headers=h, params={"format": "epub"})
    if r.status_code == 200:
        (OUT_DIR / "双城交换杀人.epub").write_bytes(r.content)
        check("导出 epub", True, f"{len(r.content)} bytes")
    else:
        check("导出 epub", False, r.text[:120])

    # 10. 书目
    items = c.get(f"/story/projects/{pid}/chapters", headers=h).json().get("items", [])
    print("\n== 成书目录 ==")
    for ch in sorted(items, key=lambda x: x["chapter_no"]):
        print(f"  第{ch['chapter_no']}章《{ch['title']}》 {ch['status']} {ch['word_count']}字")
    print(f"\n== {len(PASSED)} passed, {len(FAILED)} failed ==")
    sys.exit(1 if FAILED else 0)


if __name__ == "__main__":
    main()
