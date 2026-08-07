# ruff: noqa: T201
"""推理小说创作方法论入库：知识库文档 + 预置提示词（幂等）。"""
import sys
from pathlib import Path

import httpx

BASE = "http://localhost:8002/api/v1"
ENV_PATH = Path(r"D:\software\code\ideas\list\aigc-studio\.env")


def env(k: str) -> str:
    with open(ENV_PATH, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line.startswith(k + "="):
                return line.split("=", 1)[1].strip()
    raise KeyError(k)


MYSTERY_METHODOLOGY = """# 推理小说创作方法论（完整框架）

## 一、案件类型学（选题库）
1. 密室杀人：门反锁+无出口，重点在「密室如何成立/如何被打破」
2. 不可能犯罪：足迹消失/雪地无痕/目击矛盾
3. 暴风雪山庄：孤立环境+有限嫌疑人，社会关系即动机图谱
4. 交换杀人：互杀对方目标、动机湮灭——重点在「交换是否真实存在」
5. 叙述性诡计：时间线/身份/视角误导——重点在「揭示是否公平」
6. 不在场证明诡计：时刻表/替身/双胞胎
7. 无面尸/身份错认：尸体身份是最大谜题
8. 社会派：动机大于诡计，案件是社会切片

## 二、核心诡计库
- 时间诡计：死亡时间伪造（毒发延迟/温度/胃内容物）
- 身份诡计：一人分饰/双胞胎互换/改名换姓
- 道具诡计：凶器消失/调包/同批次物证
- 空间诡计：密室机关/通道隐藏/目击视角盲区
- 逻辑诡计：证词矛盾链/排除法陷阱/伪解答

## 三、嫌疑人设计（每个嫌疑人三件套）
1. 秘密：不愿示人的过去（与案件有微妙关联）
2. 动机：表面动机（谁都会怀疑他）+ 真实动机（只有侦探能挖出）
3. 欺骗：他会主动撒的谎（把嫌疑引向别人）
每个嫌疑人必须有一个「反转点」：当秘密揭穿时，他的嫌疑要么消失、要么加深。

## 四、线索比例（40-40-20 铁律）
- 40% 真线索：读者能凭它推出真相（时间戳/物证/矛盾证词）
- 40% 误导：指向错误方向但最终被解释（伪动机/伪时间线）
- 20% 氛围/红鲱鱼：增加阅读质感，不承担推理功能
检查：结局揭示时，每一条 40% 真线索都必须被使用；误导必须被解释而非丢弃。

## 五、写作流程（八步）
1. 案件设计：真相→诡计→误导→线索链（先于一切）
2. 精确时间表：每个关键事件精确到分钟（死亡/发现/监控/电话）
3. 嫌疑人阵容：5-6 人，各带三件套
4. 大纲：尸体→嫌疑人登场→矛盾→伪解答→反转→真相→余波
5. 逐章生成：每章只推进一个发现，保持信息量节奏
6. 审问对质：让证词在对话中互相矛盾（博弈感）
7. 校对：真相唯一/线索全解释/无强行解释/时间线自洽
8. 读者复核：公平性检查（读者能凭已给线索推出真相吗）

## 六、公平性三问（每章自检）
1. 读者此刻拥有的信息，是否足够推出某个正确结论？
2. 有没有「后知后觉」的线索（出现时无意义、揭示时才有意义）？
3. 真相揭示时，是否有任何线索被强行解释？
"""

MYSTERY_TIMELINE_GUIDE = """# 推理小说时间表设计规范

## 为什么需要时间表
时间线是推理小说的骨架：诡计（伪造死亡时间/不在场证明）与真相（两案是否同时）
都靠时间戳支撑。没有精确时间表，读者无法逆推，揭示就不公平。

## 时间表必含要素
1. 死亡时间（法医推定，注明误差）
2. 发现时间（谁发现/何时/如何发现）
3. 监控/调度记录（电梯/排班/门禁/电话）
4. 关键物证时间戳（邮戳/录音/票据）
5. 嫌疑人活动时间（含无法证实的时间段——那是密室/诡计空间）

## 使用规则
- 每个时间点必须在正文中「可见」两次以上（一次出现、一次验证）
- 时间间隔要精确：涉及诡计时用「实际间隔」而非四舍五入
- 叙述误导允许（如让读者以为两案同时），但误导必须可被时间戳推翻
- 揭示时给出「时间表复盘」：把所有时间点钉在同一张纸上

## 常见错误
- 死亡时间与发现时间混用（法医推定≠现场发现）
- 章节间时间间隔描述不一致（25 小时 vs 实际 26 小时 44 分）
- 物证时间戳只出现一次，无交叉验证
"""

PROMPT_TEMPLATES = [
    {
        "title": "推理小说案件设计",
        "content": (
            "你是推理小说主编。基于以下故事梗概设计完整案件方案，输出：\n"
            "1) 真相（唯一且自洽，一句话可复述）\n"
            "2) 核心诡计（时间线/身份/密室/交换杀人之类，说明机制）\n"
            "3) 误导设计（读者会被引向的错误方向）\n"
            "4) 线索链（严格 40-40-20：四成真线索、四成误导、两成氛围）\n"
            "5) 关键时间表（精确到分钟）\n"
            "6) 嫌疑人三件套（每个嫌疑人：秘密/表面动机/真实动机/欺骗/反转点）\n"
            "梗概：{synopsis}"
        ),
        "prompt_type": "text",
    },
    {
        "title": "推理小说八章结构",
        "content": (
            "为推理小说生成八章大纲，遵循结构：\n"
            "第1章 尸体与现场（钩子：案件发生+初步信息）\n"
            "第2章 嫌疑人登场（阵容展开，各自的三件套）\n"
            "第3章 矛盾出现（证词互相冲突，伪解答开始）\n"
            "第4章 时间线（关键时间戳浮出，读者可逆推）\n"
            "第5章 误导顶点（伪解答最可信时）\n"
            "第6章 破绽（真线索串联，误导致命伤）\n"
            "第7章 反转（真相浮出：诡计机制揭示）\n"
            "第8章 对质与余波（证据链收束+余味）\n"
            "梗概：{synopsis}"
        ),
        "prompt_type": "text",
    },
    {
        "title": "推理小说审问对质",
        "content": (
            "基于以下章节内容生成一段多角色对质场景（剧本格式：角色名：台词）：\n"
            "侦探当众审问主要嫌疑人，证词互相矛盾，对话中暴露诡计破绽\n"
            "（时间线/不在场证明/物证），每个嫌疑人的反应符合其秘密与欺骗。\n"
            "章节内容：{content}"
        ),
        "prompt_type": "text",
    },
]


def main() -> None:
    user, pwd = env("INITIAL_ADMIN_USERNAME"), env("INITIAL_ADMIN_PASSWORD")
    c = httpx.Client(timeout=120, base_url=BASE)
    token = c.post("/auth/login", json={"username": user, "password": pwd}).json()["access_token"]
    h = {"Authorization": f"Bearer {token}"}

    # 1. 知识库文档（幂等）
    existing = {d["title"] for d in c.get("/knowledge/documents", headers=h).json()}
    for title, content in (
        ("推理小说创作方法论", MYSTERY_METHODOLOGY),
        ("推理小说时间表设计规范", MYSTERY_TIMELINE_GUIDE),
    ):
        if title in existing:
            print(f"跳过（已存在）: {title}")
            continue
        r = c.post("/knowledge/documents", headers=h, json={"title": title, "content": content})
        print(("OK " if r.status_code == 200 else "FAIL ") + title, r.status_code)

    # 2. 预置提示词（幂等）
    promps = c.get("/prompts/?page_size=100", headers=h).json().get("items", [])
    p_titles = {p["title"] for p in promps}
    for tpl in PROMPT_TEMPLATES:
        if tpl["title"] in p_titles:
            print(f"跳过（已存在）: {tpl['title']}")
            continue
        r = c.post("/prompts/", headers=h, json=tpl)
        print(("OK " if r.status_code == 200 else "FAIL ") + tpl["title"], r.status_code)

    print("完成")
    sys.exit(0)


if __name__ == "__main__":
    main()
