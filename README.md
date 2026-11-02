# agent-toolbox

> 先复用后自建 —— 跨 agent 的通用工具箱。

在动手产出之前，先检索是否已有他人实现的高质量成果，**直接搬过来调用**，
而不是自己烧 token 重造一遍。

支持 Claude Code / Codex / WorkBuddy / Gemini / opencode —— 一份资产，各 agent 挂接。

---

## 快速开始

```bash
git clone <this-repo> ~/agent-toolbox
cd ~/agent-toolbox
./install.sh
```

装完后：

```bash
toolbox probe                    # 看看本机各 agent 已装了什么
toolbox lookup pdf               # 按能力标签查现成工具
toolbox run <id> ...             # 参数形状照 lookup 打印的「调用:」那一行拼
```

`toolbox lookup` 打印的调用方式是**从索引的 `entry.usage` 原样读出来的**。
CLI 不替你猜参数 —— 猜出来的提示会被直接照做，错一次就烧掉一轮。
条目没声明 `usage` 时，它会明说"未声明，先跑烟测看真实接口"。

skill 会自动挂接到各 agent 的 skills 目录，之后 agent 在产出型任务开始前会自己触发。

---

## 核心理念

### 搬进来的是工具本身

| | 做法 | token 代价 |
|---|---|---|
| ✗ 复现 | 拿到源码后读懂、改写、重写一遍 | ≈ 从零实现，外加理解成本 |
| ✓ 复用 | 装进工具箱，写薄 adapter 调用 | 接近零，仅剩装配成本 |

**复现是我们要消灭的行为。**

### 检索的单位是环节，不是任务

真实成本几乎总集中在某个具体环节（解析带合并单元格的 PDF、对齐音轨到视频帧、
把数据集切成正确的 train/val），不在任务整体上。

### 必须先搜，但不强制复用

- 产出型任务不允许跳过检索直接自建
- 搜不到合格成果就自建 —— 这是正常结果，**不算失败**

强制复用会引入更糟的东西：脆弱依赖、陌生代码、上游 breaking change。

---

## 目录结构

```
agent-toolbox/
├── index.yaml              # 工具索引（provides 是能力标签）
├── toolbox/                # CLI 实现（Python 3 标准库，零依赖）
├── tools/<id>/
│   ├── vendor/             # 别人的代码，原样，不改
│   ├── adapter.sh          # 薄适配：参数映射 + 输出约定
│   └── README.md           # 来源、许可、入口、限制
├── knowledge/<id>.md       # 不可执行的成果：流程、风格、模板
├── scripts/
│   └── toolbox-launcher.sh # CLI 启动器模板
├── skills/reuse-first/
│   └── SKILL.md            # skill 源文件（唯一一份）
└── install.sh
```

**vendor 原样，adapter 在外。** 别人的代码一个字不改 —— 改了就没法安全升级上游。

---

## CLI

| 命令 | 用途 |
|---|---|
| `toolbox list` | 列出全部工具 |
| `toolbox lookup <标签>` | 按能力标签查找（标签是技术名词，不是自然语言） |
| `toolbox run <id> [--in .. --out ..] [-- 透传]` | 调用一个工具，参数形状看 `entry.usage` |
| `toolbox probe` | 探测本机各 agent 已装能力 |
| `toolbox budget` | 检索 / 验证两本账的用量（超限退出码 3） |
| `toolbox install <源> --as <id>` | 登记一个新工具 |

加 `--json` 得结构化输出。

### 统一的是出口，不是参数名

```bash
toolbox run <id> <照 lookup「调用:」行拼出的参数>
toolbox run <id> -- <任意参数>        # 透传给 adapter
```

工具的真实参数形状写在索引的 `entry.usage` 里，由 `lookup` 原样转告。
统一成 `--in/--out` 只是部分工具的契约 —— 一段旁白文本、一个项目目录都不是文件路径。
强行统一会让 adapter 编一套假参数，索引与实现就此分家。

不变的是四条：支持 `--selftest`、有前置时支持 `--setup`、
成功时 stdout 输出产物路径或 JSON、失败时 stderr 给人话 + 非零退出码。

**纯 CLI，无协议依赖** —— 这是唯一在所有 agent 上行为完全一致的调用方式。

---

## 索引条目

```yaml
- id: pdf-table-extract
  name: PDF 表格提取（保留合并单元格）
  kind: executable            # executable | knowledge
  provides: [pdf, table-extract, csv-export]
  source:
    type: github              # github | npm | pypi | hf | local-skill | own-history
    url: https://github.com/...
    license: MIT
  entry:
    command: ./adapter.sh
    args: []
    usage: "--in <pdf 路径> --out <csv 路径>"   # 真实参数形状，lookup 原样转告
    setup: ""                                   # 有前置才填
  contract:
    input: PDF 文件路径
    output: CSV 文件路径
    limits: 扫描件不支持
  cost:
    install_minutes: 0
    smoke_test: "./adapter.sh --selftest"
  verified: true                # 仅表示登记当时烟测真跑通，且不低于 L3
  verified_at: 2026-11-02
  status: ok                    # ok | needs_setup | unavailable | broken
  broken_reason: null
  added_at: 2026-11-02
```

`provides` 是**能力标签** —— 检索按标签匹配，不按名字匹配
（名字会变、作者会改名、能力不会）。

`status` 四态：`ok` 现在能跑 / `needs_setup` 代码在位但前置未就绪（**新工具的诚实默认值**）
/ `unavailable` 来源不可达或装不上、写明恢复条件 / `broken` 实测跑不通，`run` 会拒绝。

工具之间可以声明依赖：`depends_on: <另一个 id>`。
被依赖的 vendor **只存一份** —— 例如 `remotion-timeline-builder` 铺进项目的配音脚本
直接引用 `tools/voice-over-neural-tts/vendor/`，不再复制第二份。
两份副本迟早各自漂移，那时"哪份是新的"就没人知道了。

---

## 项目级叠加

项目可自带 `.workbuddy/toolbox/` 或 `.agent-toolbox/`，其中 `index.yaml` 与 `tools/`
与全局同构。

查找时**项目级优先**：项目里若有同 `id` 条目，直接遮蔽全局条目，
避免在项目特定语境下误用通用版。

---

## 原则与反模式

### 四态决策

| 态 | 含义 | 落地 |
|---|---|---|
| **复用** | 契约契合，装进工具箱用 adapter 调用 | `tools/<id>/` |
| **借用** | 只有流程与结论有价值，无代码可调 | `knowledge/<id>.md` |
| **标杆复刻** | 需求是质感 / 风格 / "要有那种感觉" | 先跑通成品，再只换内容层 |
| **自建** | 检索无解，自己写 | 留在项目里，不进 toolbox |

**「借用」不可省略。** 有些最好的成果不是代码，而是别人已验证过的流程设计。
只判"装"与"写"的二分，会把这整类高价值复用误判成不可用。

**「标杆复刻」不可省略。** 质感不体现在契约里 —— 按"输入输出是否匹配"筛选，
只能回答"能不能"，回答不了"好不好看"。

完整规则（功能型 / 质感型分诊、静态筛查与可得性预检、验证四级阶梯 L1–L4、
检索与验证分账、12 条反模式、完成时自检）只写在
[`skills/reuse-first/SKILL.md`](skills/reuse-first/SKILL.md) 与其 `references/` 里。
本文件不复述 —— 第三份拷贝迟早会和前两份对不上。

---

## 规范在哪里

本仓库公开的规范只有三处，它们彼此一致、互为校验：

- `skills/reuse-first/SKILL.md` —— 流程与规则（唯一权威）
- `skills/reuse-first/references/*.md` —— 各环节细则
- `index.yaml` 顶部注释 —— 索引字段与 `status` / `verified` 词表

设计与决策记录（含被实战推翻的决定的原始版本与废止理由）留在本机 `docs/plans/`，
不随工具发布 —— 过程性文档属于作者，不属于被装走的那个人。

---

## 许可

MIT
