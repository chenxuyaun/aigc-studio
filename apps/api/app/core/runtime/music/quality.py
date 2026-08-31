# ruff: noqa: E501
"""Core Runtime - Music 歌词质量门（P1-1 从 api/v1/generations/music.py 抽离）。

- _repair_lyrics: 程序化修复常见结构错误（重复段落标签合并）
- _validate_lyrics: 定稿结构自检（缺段落/单薄/动机降维/抽象赋义/符号过密/押韵/作文腔…）
- _severe_checks: 判定哪些自检警告值得自动重写一轮
- _RHYME_TABLE / _RHYME_INDEX: 十三辙韵部表（同辙不同字 = 真押韵）

纯函数，无任何 I/O。
"""
from __future__ import annotations

import re


def _repair_lyrics(lyrics: str) -> str:
    """程序化修复常见结构错误：同一段落标签连续重复时合并（主歌/桥段各 1 段，副歌最多 2 遍）。

    模型常把每行都打上【主歌1】标签——把「【主歌1】A
【主歌1】B」修复为「【主歌1】A
B」；
    也用【副歌2】代替第二遍【副歌】——归一化为【副歌】（计数/校验按两遍【副歌】处理）。
    """
    if not lyrics:
        return lyrics
    lyrics = re.sub(r"【副歌[2４]】", "【副歌】", lyrics)
    out: list[str] = []
    seen_tags: dict[str, int] = {}  # 标签 → 已出现次数
    for raw in lyrics.splitlines():
        line = raw.strip()
        if not line:
            out.append("")
            continue
        m = re.match(r"^(【[^】]+】)(.*)$", line)
        if not m:
            out.append(line)
            continue
        tag, rest = m.group(1), m.group(2)
        count = seen_tags.get(tag, 0)
        # 副歌允许 2 遍；其它标签只允许 1 次；超限的并入最近一次同名段落
        limit = 2 if tag == "【副歌】" else 1
        if count >= limit:
            # 找最近一次该标签所在的行，把内容追加到其后
            for i in range(len(out) - 1, -1, -1):
                if out[i].startswith(tag):
                    out.insert(i + 1, rest.strip())
                    break
            continue
        seen_tags[tag] = count + 1
        out.append(line)
    return "\n".join(out).strip()


def _is_antithetical_hook(line: str) -> bool:
    """判断一句歌词是否是「道理对仗格言」而非「具体事件/画面」。

    特征：逗号分隔两个字数完全相等的短语，且结尾不是具体动作动词——
    如「车铃响三声，夜路短一截」「他走他的路，我补我的乐」；
    事件句（「栽进排水沟」「我那年下夜班，铃是个哑巴」）不命中。
    """
    s = (line or "").strip().rstrip("，,。")
    if not s:
        return False
    parts = re.split(r"[，,]", s)
    if len(parts) != 2:
        return False
    a, b = parts[0].strip(), parts[1].strip()
    if not a or not b:
        return False
    # 对仗：字数完全相等
    if len(a) != len(b):
        return False
    # 结尾若是具体动作动词（栽/摔/骂/扶/推/擦/按/敲/走/跑/看/听/捡/递/塞/扫），是事件句非格言
    action_tail = re.compile(r"(栽|摔|骂|扶|推|擦|按|敲|走|跑|看|听|捡|递|塞|扫)$")
    return not (action_tail.search(a) or action_tail.search(b))


def _strip_tag(line: str) -> str:
    """去掉行首的【段落标记】，返回正文；无标记则原样返回（保留首尾空白去除）。"""
    m = re.match(r"^【[^】]*】", line.strip())
    return line.strip()[m.end() :].strip() if m else line.strip()


def _segment_text(lyrics: str, tag: str) -> str:
    """取【tag】到下一个【 之间的文本。"""
    idx = lyrics.find(tag)
    if idx < 0:
        return ""
    nxt = lyrics.find("【", idx + len(tag))
    return lyrics[idx + len(tag) : nxt if nxt > 0 else len(lyrics)]


def _tail_char(line: str) -> str:
    """句尾最后一个汉字（跳过标点/括号）。"""
    for ch in reversed(line):
        if "\u4e00" <= ch <= "\u9fff":
            return ch
    return ""


def _syllable_count(line: str) -> int:
    """句子的音节数 ≈ 汉字数（唱感：旋律对齐的粗略单位）。"""
    return sum(1 for ch in line if "\u4e00" <= ch <= "\u9fff")


# 十三辙韵部表（歌词句尾字 → 辙）：用于押韵校验（比"同字重复"高级——同辙不同字=真押韵）
_RHYME_TABLE: dict[str, tuple[str, ...]] = {
    "发花": ("啊", "巴", "吧", "妈", "花", "华", "家", "牙", "沙", "大", "发", "啥", "拉", "哇", "瓜", "夸", "抓", "夏", "下", "画", "话", "他", "她", "它", "怕", "答", "查", "加", "打", "马", "假"),
    "梭波": ("波", "坡", "佛", "哥", "科", "河", "车", "蛇", "火", "果", "多", "罗", "做", "错", "桌", "说", "托", "过", "国", "活", "货", "落", "朵", "热", "我", "坐", "默", "可"),
    "乜斜": ("别", "灭", "爹", "贴", "列", "姐", "切", "些", "夜", "月", "雪", "缺", "约", "学", "绝", "血", "借", "写", "谢", "叶", "叠", "铁", "节", "解", "结", "些"),
    "姑苏": ("屋", "无", "夫", "服", "古", "鼓", "哭", "苦", "路", "鹿", "兔", "土", "苏", "足", "住", "数", "处", "湖", "炉", "孤", "读", "书", "目", "暮", "骨"),
    "一七": ("衣", "比", "米", "低", "梯", "尼", "离", "理", "力", "期", "七", "齐", "西", "地", "第", "替", "机", "鸡", "记", "气", "日", "自", "此", "思", "词", "你", "里", "起", "去", "雨", "语", "遇", "女", "绿", "曲", "虚", "许", "序", "鱼", "依", "意", "易", "义", "细", "急", "滴", "迹", "系", "喜", "已", "以", "椅", "疑"),
    "怀来": ("哀", "爱", "来", "开", "海", "带", "白", "买", "快", "怪", "外", "帅", "坏", "呆", "待", "猜", "才", "菜", "台", "抬", "拍", "排", "牌", "麦", "卖"),
    "灰堆": ("杯", "飞", "非", "雷", "累", "内", "黑", "背", "美", "妹", "对", "队", "回", "会", "最", "追", "水", "吹", "归", "泪", "碎", "醉", "亏", "危", "灰", "赔", "配"),
    "遥条": ("高", "好", "老", "刀", "早", "草", "跑", "抱", "跳", "笑", "桥", "小", "叫", "鸟", "了", "到", "道", "少", "找", "扫", "烧", "绕", "腰", "要", "药", "票", "飘", "桥", "潮", "照", "烧"),
    "由求": ("头", "口", "走", "楼", "愁", "收", "手", "有", "又", "酒", "久", "牛", "留", "流", "修", "丢", "秋", "周", "州", "豆", "够", "后", "厚", "扣", "漏", "瘦", "透", "邮", "游"),
    "言前": ("山", "寒", "看", "站", "兰", "散", "南", "三", "干", "边", "天", "年", "连", "前", "间", "见", "远", "全", "选", "眼", "脸", "烟", "然", "断", "短", "船", "传", "转", "乱", "慢", "满", "暖", "半", "班", "盘", "安", "案", "岸", "喊", "还", "换", "宽", "关", "管", "惯", "圆", "愿", "怨", "原", "源"),
    "人辰": ("人", "门", "分", "很", "根", "真", "深", "身", "针", "心", "新", "今", "金", "因", "音", "春", "村", "问", "温", "闻", "文", "吻", "尘", "沉", "陈", "臣", "神", "痕", "恨", "认", "忍", "润", "顺", "损", "存", "困", "魂", "昏", "混", "尽", "近", "进", "禁", "紧", "斤", "锦", "亲", "琴", "勤", "林", "邻", "临", "民", "敏", "品", "频", "贫", "云", "运", "韵", "均", "群"),
    "江阳": ("光", "乡", "香", "方", "房", "堂", "长", "张", "场", "汤", "刚", "康", "黄", "忙", "忘", "王", "床", "常", "窗", "唱", "伤", "霜", "双", "爽", "想", "向", "像", "响", "相", "香", "凉", "量", "亮", "两", "辆", "江", "讲", "强", "墙", "枪", "让", "浪", "放", "望", "往", "网", "阳", "洋", "样", "羊", "央", "扬", "羊"),
    "中东": ("风", "灯", "更", "声", "生", "成", "城", "星", "行", "明", "平", "名", "空", "红", "东", "中", "同", "龙", "用", "梦", "痛", "送", "松", "钟", "终", "重", "虫", "冲", "通", "工", "公", "功", "共", "宫", "弓", "洪", "宏", "恒", "衡", "冷", "岭", "零", "灵", "领", "另", "令", "停", "听", "庭", "晴", "情", "清", "请", "庆", "轻", "倾", "琼", "荣", "容", "融", "荣"),
}

# 字 → 辙 的倒排（查句尾字属于哪一辙）
_RHYME_INDEX: dict[str, str] = {}
for _z, _chars in _RHYME_TABLE.items():
    for _c in _chars:
        _RHYME_INDEX.setdefault(_c, _z)


def _validate_lyrics(lyrics: str) -> list[str]:
    """定稿结构自检：返回警告列表（缺段落/标签重复/副歌次数/字数/押韵提示）。"""
    warnings: list[str] = []
    text = lyrics or ""
    # 段落存在性 + 次数（主歌1/主歌2/桥段各 1 次，副歌恰好 2 次）
    counts: dict[str, int] = {}
    for tag in ("【主歌1】", "【副歌】", "【主歌2】", "【桥段】"):
        counts[tag] = text.count(tag)
        if counts[tag] == 0:
            warnings.append(f"缺少{tag}段落")
    if counts["【主歌1】"] > 1:
        warnings.append(f"【主歌1】出现了 {counts['【主歌1】']} 次（应合并为 1 段）")
    if counts["【主歌2】"] > 1:
        warnings.append(f"【主歌2】出现了 {counts['【主歌2】']} 次（应合并为 1 段）")
    if counts["【桥段】"] > 1:
        warnings.append(f"【桥段】出现了 {counts['【桥段】']} 次（应合并为 1 段）")
    if counts["【副歌】"] < 2:
        warnings.append("副歌重复次数不足（应至少 2 次）")
    elif counts["【副歌】"] > 3:
        warnings.append(f"副歌出现了 {counts['【副歌】']} 次（应为 2-3 次）")
    if 0 < len(text) < 500:
        warnings.append(f"歌词偏短（{len(text)}字，完整长曲应 900-1100 字两段式）——这是短版不是长曲："
                        "补【主歌3】/加长主歌句数与副歌遍数/加厚细节（物件/动作/声音），Part A+B 合计到 5-6 分钟")
    # 段落单薄检测：句数不足 = 骨架化（每段只剩两三句口号式短句，没有细节承载）
    for tag, min_lines in (("【主歌1】", 5), ("【主歌2】", 5), ("【主歌3】", 4), ("【副歌】", 4), ("【桥段】", 3), ("【预副歌】", 2)):
        seg_lines = [ln.strip() for ln in _segment_text(text, tag).splitlines() if ln.strip()]
        if seg_lines and len(seg_lines) < min_lines:
            warnings.append(
                f"{tag}单薄（仅 {len(seg_lines)} 句，应 ≥{min_lines} 句）——细节被砍光了，"
                "每段要写够物件/动作/声音的具体细节，禁止骨架式口号"
            )
    # 人物动机降维检测：丧亲意象 + 反复守/等/留，但几乎没有职业/劳动动作 = 悲情覆盖价值
    # （人物价值层级坍缩：人物被悲伤解释吞掉，缺少信仰/使命/职业伦理支撑）
    _LOSS_WORDS = ("亡妻", "去世", "走丢", "没救上来", "牺牲", "不在了", "出的事", "翻船", "淋雨走丢", "再没回来", "走的那年", "没接住", "没等到")
    _LINGER_WORDS = ("守", "等", "留", "念")
    _LABOR_WORDS = (
        "修", "补", "焊", "扫", "检", "量", "算", "装", "卸", "递", "撑", "擦", "磨",
        "捡", "纳", "缝", "煮", "熬", "抄", "记", "值", "倒", "盛", "捞", "洗", "晾",
        "拆", "绑", "缠", "拧", "敲", "刮", "浇", "筑", "搬", "扛", "推", "铲", "刨",
    )
    loss_hits = [w for w in _LOSS_WORDS if w in text]
    linger_hits = [w for w in _LINGER_WORDS if w in text]
    labor_hits = [w for w in _LABOR_WORDS if w in text]
    if loss_hits and len(linger_hits) >= 2 and len(labor_hits) <= 1:
        warnings.append(
            "人物动机降维（悲情覆盖价值）：出现丧亲意象（"
            + "、".join(loss_hits[:3])
            + "）+ 反复「守/等/留」，但全曲几乎没有职业/劳动动作——"
            "人物被悲伤解释吞掉，加职业逻辑与具体劳动细节（修/补/检/扫/煮…），"
            "让创伤成为信仰的起点而非动机的全部"
        )
    # 抽象赋义检测：自然物 + 心理/抽象动词（草认得/山记得/河知道）=
    # 概念化拟人（Meaning Imposition）——把情感抽象贴给自然物，没有可感画面。
    # 拟人必须可感：草弯腰/叶刮脚踝是画面；"认得/记得"是概念，是作者赋义。
    _NATURE = ("草", "山", "河", "江", "风", "雨", "路", "灯", "树", "水", "云",
               "月", "星", "雪", "桥", "石", "街", "巷", "光", "雾", "霜", "浪", "谷", "岸")
    _MIND_VERBS = ("认得", "记得", "知道", "明白", "听懂", "听见", "看见", "等着",
                   "想起", "忘了", "念着", "记着", "守着", "懂得", "哭了", "笑了", "懂了", "作证", "见证")
    _ABSTRACT_PATTERN = re.compile(
        "(" + "|".join(_NATURE) + ")(" + "|".join(_MIND_VERBS) + ")"
    )
    if _ABSTRACT_PATTERN.search(text):
        hits = list(set(_ABSTRACT_PATTERN.findall(text)))[:3]
        warnings.append(
            "抽象赋义（自然物+心理动词："
            + "、".join(a + b for a, b in hits)
            + "…）：把情感抽象贴给自然物是作者赋义，不是画面——"
            "拟人必须可感（草弯腰/叶刮脚踝/风把信纸吹到门槛），"
            "禁止「草认得/山记得/河知道」式概念化拟人"
        )

    # 符号过密检测：意象全在第一联想语义空间（雨=思念/桥=人生/旧物=回忆）
    _SYMBOL_WORDS = (
        "雨", "桥", "伞", "灯", "旧", "故人", "十年", "远方", "霜", "青瓦", "江南", "烟雨", "风",
    )
    symbol_hits = [w for w in _SYMBOL_WORDS if w in text]
    if len(symbol_hits) >= 6:
        warnings.append(
            "符号过密（"
            + "、".join(symbol_hits[:6])
            + "）：意象全在第一联想语义空间，换现实/职业/技术维度；"
            "物件首先是物件，意义从使用中涌现"
        )

    # 押韵提示：任一段内句尾字完全相同的重复韵脚（如整段全押"光"）
    # 每段最多取前 4 行检测——模型常把两遍副歌粘连在同一标签下（重复段句尾必相同，
    # 不取前几行会把"副歌重复"误报成"押韵偷懒"；单遍副歌/主歌标准 3-4 句）
    for tag in ("【主歌1】", "【副歌】", "【主歌2】", "【桥段】"):
        seg = _segment_text(text, tag)
        lines = [ln.strip() for ln in seg.splitlines() if ln.strip()][:4]
        tails = [_tail_char(ln) for ln in lines if _tail_char(ln)]
        dup = {t for t in tails if tails.count(t) >= 3}
        if dup and len(tails) >= 3:
            warnings.append(
                f"{tag}句尾反复用「{''.join(sorted(dup))}」字（押韵偷懒），建议同韵部换不同字"
            )
        # 无韵检测（十三辙）：段内句尾字去重后 ≥4 个且零同辙 = 明显无韵
        # 同辙不同字 = 真押韵；同字重复被上面"押韵偷懒"接住
        uniq = list(dict.fromkeys(tails))
        if len(uniq) >= 4:
            rhyme_z = {_RHYME_INDEX.get(u) for u in uniq}
            rhyme_z.discard(None)
            if len(rhyme_z) == len(uniq) and len(rhyme_z) >= 4 and not dup:
                warnings.append(
                    f"{tag}无韵（句尾 {len(uniq)} 个尾字互不押韵）："
                    "按十三辙选韵（如言前辙 an/ian：山/天/年/见），每段至少两处同辙句尾"
                )
    # 空洞赞颂/鸡汤词检测：赞颂句式填空词（步伐/鼓点/星火/路标/光芒/梦想/辉煌/灯塔/力量）
    # 出现 ≥2 个不同词即报警——对模糊对象喊口号或把苦难鸡汤化
    _HOLLOW_WORDS = (
        "步伐", "鼓点", "星火", "路标", "光芒", "梦想", "辉煌", "灯塔", "力量", "时代",
        "灿烂", "绽放", "闪耀", "温柔", "希望", "美好", "救赎", "远方",
    )
    hollow_hits = [w for w in _HOLLOW_WORDS if w in text]
    if len(hollow_hits) >= 2:
        warnings.append(
            f"空洞赞颂/鸡汤词过密（{''.join(hollow_hits)}），"
            "疑似对模糊对象喊口号或把苦难浪漫化：换成具体动作、物件与人物对话"
        )
    # 作文腔检测：散文/文艺腔高频词——歌词应是"能唱的人话"，不是散文诗
    # 出现 ≥4 处说明语言文人腔过重，句子飘在抽象里，普通人唱不出来
    _LITERARY_WORDS = (
        "呼吸", "温热", "悄悄", "静静", "沉默", "未凉", "仿佛", "如同", "呢喃",
        "低语", "余温", "斑驳", "澄澈", "氤氲", "缱绻", "喟叹", "游走", "轻颤",
    )
    literary_hits = [w for w in _LITERARY_WORDS if w in text]
    if len(literary_hits) >= 4:
        warnings.append(
            f"作文腔过重（{''.join(literary_hits[:8])}…），"
            "歌词是能唱出来的人话，不是散文诗：改口语化，让'人'直接说话和动作"
        )
    # 暖词复用检测：用「热乎/焐软/焐热/暖烘烘」这类笼统暖词给情感收尾 = 词汇偷懒（把情感抽象成温度）
    _WARM_CRUTCH = ("热乎", "焐软", "焐热", "暖烘烘")
    warm_hits = [w for w in _WARM_CRUTCH if w in text]
    if warm_hits:
        warnings.append(
            f"暖词复用（{''.join(warm_hits)}）：情感落点用笼统暖词收尾（把情感抽象成'温度'），"
            "换成具体的物件/动作/声音，禁止'热/暖/焐'从头用到尾"
        )
    # 点睛检测：全程第三人称白描（无直接引语/无第一人称心声）→ 观察报告式，缺心口之言
    # 引号兼容：中文引号（“”「」）与 ASCII 双引号都算引语（模型常输出英文引号）
    has_dialogue = any(
        mark in text
        for mark in ("“", "「", "”", "」", '"', "说：", "想：", "在心里", "对自己说")
    )
    if not has_dialogue and "我" not in text:
        warnings.append(
            "全程白描缺点睛：歌词没有人物自己的声音（直接引语/第一人称心口之言），"
            "只有动作和物件——加一句人物直接说的话或情感点破"
        )
    # 钩子事件化检测：副歌首行若是「道理对仗格言」（车铃响三声，夜路短一截式）而非具体事件 → 报警
    hook_lines = [
        ln.strip()[len("【副歌】") :].strip()
        for ln in text.splitlines()
        if ln.strip().startswith("【副歌】") and len(ln.strip()) > len("【副歌】")
    ]
    if hook_lines and _is_antithetical_hook(hook_lines[0]):
        warnings.append(
            "副歌钩子是「道理对仗格言」（如'车铃响三声，夜路短一截'式总结陈词）而非具体事件/画面——"
            "把钩子改成具体动作或画面（如'栽进排水沟''我那年下夜班，铃是个哑巴'）"
        )
    # 自报家门检测：歌词行首（去段落标记后）以「我是XX」+名字开头（小说人物卡式自报）→ 报警
    # 「我是真的/想说/就是」这类口语连用排除，避免误伤
    _SELF_INTRO_STOP = {"真的", "想说", "想要", "要说", "就是", "不是", "一个", "这样", "那样"}
    _SELF_INTRO_RE = re.compile(r"^我是([一-龥]{2,3})[，,、。\s]")
    for raw in text.splitlines():
        ln = _strip_tag(raw)
        m = _SELF_INTRO_RE.match(ln)
        if m and m.group(1) not in _SELF_INTRO_STOP:
            warnings.append(
                "歌词自报家门（「我是XX」人物卡写法）：歌词不是人物小传，"
                "人物的具体性靠物件/动作/细节传递——删掉「我是XX」自报，名字不进歌词正文"
            )
            break
    # 散文长句检测：单句塞 ≥3 个并列信息（逗号/顿号/分号）→ 散文不是歌词，短行断句
    prose_hits = []
    for raw in text.splitlines():
        ln = _strip_tag(raw)
        if not ln:
            continue
        breaks = ln.count("，") + ln.count(",") + ln.count("、") + ln.count("；") + ln.count(";")
        if breaks >= 3:
            prose_hits.append(ln)
    if prose_hits:
        warnings.append(
            f"散文长句（歌词不是散文，一句塞了多个并列信息）：「{prose_hits[0][:16]}…」等 {len(prose_hits)} 处——"
            "拆成短行，一句只说一件事"
        )
    # 绝对句长超限检测：单句 > 15 汉字（歌词感铁律——5-12 字为主，禁超 15 字）。
    # 段内相对比较查不出"整段都长"（叙事诗式），必须按绝对阈值拦。
    for raw in text.splitlines():
        ln = _strip_tag(raw)
        if not ln:
            continue
        n = _syllable_count(ln)
        if n > 16:
            warnings.append(
                f"长句（{n}字，歌词感铁律禁超16字）：「{ln[:20]}…」——"
                "拆成 5-12 字短句，长句是叙事诗/散文，不是能跟拍子唱的歌词"
            )
            break  # 报一处即可，重写轮会带全文
    # 唱感检查：段内句长（音节数=汉字数）应均衡——某句明显长/短于该段均值，
    # 旋律对不齐（6 秒一句的副歌被 12 字长句压垮）
    # 按行级处理：同标签所有行合并统计（重复标签场景不被 _segment_text 截断漏检）
    for tag in ("【主歌1】", "【副歌】", "【主歌2】", "【桥段】"):
        contents = [
            ln.strip()[len(tag) :].strip()
            for ln in text.splitlines()
            if ln.strip().startswith(tag) and len(ln.strip()) > len(tag)
        ]
        lens = [(_syllable_count(c), c) for c in contents if _syllable_count(c) > 0]
        if len(lens) >= 3:
            avg = sum(n for n, _ in lens) / len(lens)
            for n, c in lens:
                if abs(n - avg) > max(4, avg * 0.4):
                    warnings.append(
                        f"{tag}唱感不齐：「{c[:18]}…」{n}字，段内均值{avg:.0f}字——"
                        "长句会压垮旋律，建议拆分或删减"
                    )
    return warnings


def _severe_checks(checks: list[str]) -> bool:
    """自检中值得自动重写的严重问题（空洞赞颂/作文腔/缺点睛/格言钩子/缺段落/押韵偷懒等）。"""
    return any(
        ("空洞赞颂" in c)
        or ("作文腔" in c)
        or ("点睛" in c)
        or ("格言" in c)
        or ("缺少" in c)
        or ("副歌重复次数不足" in c)
        or ("押韵偷懒" in c)
        or ("无韵" in c)
        or ("长句" in c)
        or ("偏短/单薄" in c)
        or ("太短" in c)
        or ("动机降维" in c)
        or ("符号过密" in c)
        or ("抽象赋义" in c)
        or ("单薄" in c)
        or ("废稿" in c)
        or ("自报家门" in c)
        or ("散文长句" in c)
        or ("暖词复用" in c)
        for c in checks
    )
