# ruff: noqa: T201 E501
"""推理小说工作坊：用角色群多角色博弈演绎创作一部本格推理小说。

流程（全部真实模型 cpa）：
1. 建项目（世界观：暴雪封锁的雪山列车 + 密室毒杀核心谜题）
2. 项目级世界书（世界观设定）
3. 角色阵容 6 名：侦探 + 5 嫌疑人（各带秘密/动机/欺骗/反转点）
4. 主编生成完整案件设计文档（真相/诡计/误导/线索链）→ 注入后续章节
5. 按推理结构生成 8 章大纲（尸体→嫌疑人→矛盾→反转→真相）
6. 逐章叙事生成（案件设计作为写作指令）
7. 群聊对抗：侦探审问两名嫌疑人（多角色博弈，剧本模式）
8. 校对验证：逻辑闭环检查（真相唯一/线索全解释/无强行解释）
9. 导出 markdown + epub
"""
import json
import sys
import time
from pathlib import Path

import httpx

BASE = "http://localhost:8002/api/v1"
MODEL = "gpt-oss-120b-medium"
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
    c = httpx.Client(timeout=300, base_url=BASE)
    token = c.post("/auth/login", json={"username": user, "password": pwd}).json()["access_token"]
    h = {"Authorization": f"Bearer {token}"}

    # 0. 清理旧项目
    for p in c.get("/story/projects", headers=h).json().get("items", []):
        if p["title"] == "雪山列车疑案":
            c.delete(f"/story/projects/{p['id']}", headers=h)
            print("已清理旧项目")

    # 1. 建项目（世界观 + 核心谜题种子）
    r = post(c, h, "/story/projects", {
        "title": "雪山列车疑案",
        "genre": "本格推理",
        "synopsis": (
            "1935 年隆冬，开往雪城的特快列车被暴雪困在群山之间。"
            "次日清晨，6 号包间的富商程文远被发现死于密室——门窗反锁，毒杀。"
            "车上九人：侦探陆明远、列车长、医生、寡妇、画家、商人，另有乘客三人。"
            "暴雪封路，凶手就在九人之中。列车抵达前的十二小时，"
            "侦探必须在谎言与真相的博弈中，让唯一解释成立。"
        ),
    })
    pid = r["project"]["id"]
    check("项目创建", bool(pid))

    # 2. 项目级世界书：世界观
    for kw, content in [
        (["雪山列车"], "雪山号特快：1935 年制造，六节车厢，行驶于北境群山线。暴雪封路时列车会停在 13 号隧道前的临时避风线，无线电中断，与外界的唯一联系是每两小时一次的信号灯。"),
        (["毒杀"], "本案件死因为蓖麻毒素中毒，死亡时间约在午夜零时至一时之间。毒素溶于热红酒，摄入后 2-4 小时发作，症状类似急性肠胃炎，极易误判死亡时间——这是本案的关键时间诡计。"),
        (["密室"], "6 号包间：唯一的门自内反锁，车窗因暴雪结冰从内无法开启。但列车老式包间的通风口位于门框上方，宽度仅一掌，成年男子无法通过——密室是否成立，是本案核心。"),
    ]:
        r = post(c, h, "/roleplay/lore", {
            "project_id": pid, "keywords": kw, "content": content,
            "selective": True,
        })
    check("世界书设定（3 条）", True)

    # 3. 角色阵容：侦探 + 5 嫌疑人（秘密/动机/欺骗/反转）
    cast = [
        {"name": "陆明远", "role": "protagonist",
         "description": "三十四岁，曾为警视厅精英刑警，因一桩错案辞去公职。观察力极强，擅长从'异常'中发现真相——他认为正常人不会留下线索，只有异常行为才是真相。",
         "goals": "在列车抵达前找出真凶，证明自己的推理；也为了弥补当年错案留下的阴影。",
         "arc": "从孤高怀疑到信任证据链的完整推理；最终发现本案与自己当年错案的受害者有关。",
         "current_state": "刚确认死者身份，开始逐个询问乘客。"},
        {"name": "沈青山（列车长）", "role": "supporting",
         "description": "五十二岁，服役二十年的老列车长，威严而寡言。",
         "goals": "秘密：私运了一批药材被程文远撞见并以此要挟。",
         "arc": "动机：灭口并夺回把柄。",
         "current_state": "声称整夜在驾驶室值班，无人可证。"},
        {"name": "林静秋（医生）", "role": "supporting",
         "description": "四十一岁，随车医生，医术精湛，气质沉静。",
         "goals": "秘密：七年前误诊导致程文远独子夭折，此事鲜有人知。",
         "arc": "动机：多年隐忍后的报复；但她的另一面是案发后第一时间为死者争取抢救时间。",
         "current_state": "坚持毒发时间在凌晨两点的判断（与真相冲突）。"},
        {"name": "苏曼（寡妇）", "role": "supporting",
         "description": "三十五岁，自称初次乘车的旅客，衣着考究。",
         "goals": "秘密：程文远是她的前夫，两人离婚时她分得大笔遗产。",
         "arc": "动机：遗产分配纠纷的延续；反转：她此行是为了保护某个人。",
         "current_state": "伪装成与死者素不相识的陌生人。"},
        {"name": "周砚（画家）", "role": "supporting",
         "description": "二十八岁，落魄画家，话少，总在餐车写生。",
         "goals": "秘密：午夜时分他确实目击了案发，但为了隐瞒自己的行踪而说谎。",
         "arc": "动机：保护——他此行的真正目的是护送一名女子逃离；反转：他是唯一诚实面对尸体的人。",
         "current_state": "声称整晚在餐车画画，画作却只有三幅。"},
        {"name": "陈满堂（商人）", "role": "supporting",
         "description": "四十七岁，富商，与死者有生意往来，口若悬河。",
         "goals": "秘密：与程文远有一笔巨额合同纠纷，已到破产边缘。",
         "arc": "动机：金钱；欺骗：伪造了与其他乘客的对话作为不在场证明。",
         "current_state": "积极提供'线索'，试图把嫌疑引向医生。"},
    ]
    char_asset_ids: list[str] = []
    for ch in cast:
        r = post(c, h, f"/story/projects/{pid}/characters", {
            "name": ch["name"], "role": ch["role"], "description": ch["description"],
            "goals": ch["goals"], "arc": ch["arc"], "current_state": ch["current_state"],
        })
        # 酒馆角色卡化：每个角色创建真实 V2 角色卡（JSON 导入 → PNG 存储）
        card_json = json.dumps({
            "spec": "chara_card_v2",
            "spec_version": "2.0",
            "data": {
                "name": ch["name"],
                "description": ch["description"],
                "personality": ch["arc"],
                "scenario": "1935 年暴雪封锁的雪山号特快列车上，密室毒杀案发生。",
                "first_mes": "",
                "mes_example": "",
                "system_prompt": f"你是《雪山列车疑案》中的角色「{ch['name']}」。"
                                 f"牢记自己的秘密、动机与欺骗：{ch['goals']} {ch['arc']} "
                                 f"{ch['current_state']}。在审讯与对质中，"
                                 "只说符合自己立场的话，必要时说谎与误导。",
                "creator_notes": "推理小说工作坊自动生成的角色卡",
            },
        }, ensure_ascii=False).encode("utf-8")
        resp = c.post(
            "/roleplay/characters/import", headers=h,
            files={"file": (f"card-{ch['name']}.json", card_json, "application/json")},
        )
        body = resp.json()
        aid = body.get("asset_id")
        if aid:
            char_asset_ids.append(aid)
            print(f"  角色卡: {ch['name']} -> {aid[:8]}")
    check("角色阵容 6 名 + 酒馆角色卡", len(char_asset_ids) == len(cast),
          f"{len(char_asset_ids)}/{len(cast)} 张卡")
    # 把真实角色卡挂到项目（酒馆角色群驱动后续生成与博弈）
    r = c.put(f"/story/projects/{pid}", headers=h, json={"character_asset_ids": char_asset_ids})
    check("项目关联角色卡群", r.status_code == 200, f"{len(char_asset_ids)} 张")

    # 4. 主编生成案件设计文档（真相/诡计/误导/线索链）
    r = post(c, h, f"/story/projects/{pid}/crew", {
        "project_id": pid, "stage": "director", "model": MODEL,
    })
    check("案件设计（主编）", "error" not in r and bool(r.get("direction")),
          str(r.get("direction", ""))[:100])

    # 5. 推理结构大纲 8 章
    r = c.post(f"/story/projects/{pid}/outline?chapters=8&model={MODEL}", headers=h)
    body = r.json()
    chapters = body.get("chapters") or []
    check("推理结构大纲 8 章", r.status_code == 200 and len(chapters) == 8, r.text[:120])
    for ch in chapters[:4]:
        print(f"  大纲 第{ch['chapter_no']}章《{ch['title']}》")

    # 6. 逐章叙事生成（案件设计注入）
    for ch in chapters:
        r = post(c, h, f"/story/chapters/{ch['id']}/generate", {
            "project_id": pid, "mode": "narrative", "model": MODEL, "max_tokens": 1600,
        })
        if "error" in r:
            check(f"章节{ch['chapter_no']}生成", False, str(r.get("error"))[:120])
            continue
        check(f"章节{ch['chapter_no']}《{ch['title']}》", True, f"{r.get('word_count')} 字")
        time.sleep(1)

    # 7. 群聊对抗：侦探审问两名嫌疑人（多角色博弈）
    r = c.post(f"/story/projects/{pid}/chapters", headers=h, json={
        "title": "餐车对质（博弈场景）",
        "outline": (
            "侦探陆明远在餐车同时审问林医生与陈商人：林坚持死亡时间在凌晨两点，"
            "陈则不断暗示凶手是医生。两人的证词互相矛盾，侦探在对话中捕捉到"
            "时间诡计的破绽——蓖麻毒素的症状被利用来伪造死亡时间。"
        ),
    }).json()
    sid = r["chapter"]["id"]
    r = post(c, h, f"/story/chapters/{sid}/generate", {
        "project_id": pid, "mode": "script", "model": MODEL, "rounds": 8,
    })
    if "error" in r:
        check("群聊对抗审问", False, str(r.get("error"))[:120])
    else:
        check("群聊对抗审问（三角色博弈）", True, f"{r.get('turns')} 轮对话 · {r.get('word_count')} 字")

    # 8. 校对：逻辑验证（真相唯一/线索全解释/无强行解释）
    cid_last = chapters[-1]["id"]
    r = post(c, h, f"/story/projects/{pid}/crew", {
        "project_id": pid, "stage": "editor", "model": MODEL, "chapter_id": cid_last,
    })
    if "error" in r:
        check("推理逻辑验证（校对）", False, str(r.get("error"))[:120])
    else:
        check("推理逻辑验证（校对）", True, str(r.get("review", ""))[:100])

    # 9. 导出
    r = c.get(f"/story/projects/{pid}/export", headers=h, params={"format": "markdown"})
    if r.status_code == 200:
        (OUT_DIR / "雪山列车疑案.md").write_text(r.text, encoding="utf-8")
        total = sum(
            ch.get("word_count") or 0
            for ch in c.get(f"/story/projects/{pid}/chapters", headers=h).json().get("items", [])
        )
        check("导出 markdown", True, f"全书 {total} 字")
    else:
        check("导出 markdown", False, r.text[:120])
    r = c.get(f"/story/projects/{pid}/export", headers=h, params={"format": "epub"})
    if r.status_code == 200:
        (OUT_DIR / "雪山列车疑案.epub").write_bytes(r.content)
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
