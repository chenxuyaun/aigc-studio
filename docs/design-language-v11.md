# saiOS v11 设计语言「宣纸 × 青瓷」（全站重构北极星）

> 依据 frontend-design skill 两遍式确立。所有页面重构以本文档为准；
> 与本文档冲突的既有样式，一律收敛到本文档。

## 一、题材根源（为什么是青瓷）

saiOS 是创作工坊：用户派活（写作/绘画/音乐/视频），AI 出卷（产出作品）。
视觉母题取**东方文房**——宣纸、青瓷、玄墨、朱砂钤印。这不是装饰偏好，
而是把「创作→产出」的产品叙事翻译成材质语言：纸是等待被书写的白，
青瓷是工匠的釉色，墨是内容本身，印是完成的确认。

## 二、色（四色纪律，全站只允许这四个色相）

| 令牌 | 值 | 用途 | 禁止 |
|---|---|---|---|
| 宣纸 `--color-background` | #F9F8F6 / 暗 #111215 | 底 | — |
| 玄墨 `--color-ink/foreground` | #141518 / 暗 #f0f2f5 | 正文、实心按钮底 | — |
| 青瓷 `--color-primary` | #2f6359 / 暗 #448275 | **唯一强调色**：主按钮、激活态、链接、焦点 | 不许出现第二个彩 |
| 朱砂 `--color-danger` | #a82e35 / 暗 #c23b43 | 仅危险动作（删除/停止/报错） | 不许当点缀装饰 |

- 语义色 success/info 仅用于系统状态（成功/信息徽标），不做装饰。
- **任何 purple/amber/pink/teal/cyan 硬编码 = 违规**，一律归一到上表。
- 灰阶走 surface/muted/border 令牌，不允许裸 rgba 黑白值（阴影除外）。

## 三、字（衬线只用于「题」）

- **衬线**（Fraunces + Noto Serif SC, `font-serif`）：页面 h1、场所名、大数字题。
  衬线是页面的声音，每页最多出现一处大题。
- **无衬线**（系统栈）：正文、控件、表格。
- 等宽：仅代码/模型名/任务 id。
- 层级三级：题(text-2xl 衬线) / 文(text-sm) / 注(text-[11px] muted)。
  **字号地板 10px**；不允许 uppercase tracking 宽距的 eyebrow 标签
  （「技能」「模型:」这类小标签用 sentence case + muted 即可）。
- 标题加 `text-balance`；长文容器 `min-w-0` + truncate。

## 四、形（容器与控件）

- 页面容器：纸卡 `rounded-2xl border-line bg-surface shadow-zen`。
- 控件（按钮/输入）：`rounded-xl`。
- 胶囊 `rounded-full`：仅分段切换（tab/pills），不做按钮默认。
- **每页一个记忆点**（Spend your boldness in one place）：
  - 派活中枢 = 中央命题卡
  - 创作工坊 = 驾驶舱 HUD（收敛为墨+青瓷，去扫描线动效）
  - 资产藏馆 = tab 长卷（胶囊横向卷轴）
  - 角色宇宙 = 对话场（气泡纸卡）
  其余一切保持安静：无渐变、无光晕、无玻璃拟态、无入场动画。

## 五、动（只回应动作）

- 允许：hover 颜色变化（transition-colors）、开合展开、操作确认。
- 禁止：页面加载入场序列、每卡 hover 上浮/缩放、循环脉冲
  （加载中 spinner 除外）、`transition-all`、装饰性粒子/光晕/扫描线。
- `prefers-reduced-motion` 下全部静止（全局已兜底）。

## 六、图标与文案

- 图标只用 lucide 线性（`aria-hidden`）。**emoji 不做功能图标**；
  正文叙事里也不放（快捷键提示等纯文字）。
- 按钮说做什么：「生成出卷」不是「提交」；「新建创作项目」不是「+」。
- 空态是邀请：「还没有作品——派第一件活」+ 指向动作的按钮。
- 错误说怎么修，不道歉不模糊。

## 七、检查清单（每个页面重构完成跑一遍）

1. 除青瓷外无彩色？（渐变/发光/emoji 图标清零）
2. 衬线只出现在题？（无 uppercase eyebrow、无 9px 字）
3. 动效只在动作反馈？（无 transition-all、无循环脉冲）
4. 图标全 lucide + aria-hidden？
5. 按钮文案是动词短语？空态有邀请？
6. 焦点可见（focus-visible ring）、触达目标 ≥40px？
