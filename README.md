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
toolbox run <id> --in <输入> --out <输出>
```

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
├── docs/plans/             # 设计文档
└── install.sh
```

**vendor 原样，adapter 在外。** 别人的代码一个字不改 —— 改了就没法安全升级上游。

---

## CLI

| 命令 | 用途 |
|---|---|
| `toolbox list` | 列出全部工具 |
| `toolbox lookup <标签>` | 按能力标签查找（标签是技术名词，不是自然语言） |
| `toolbox run <id> --in .. --out ..` | 调用一个工具 |
| `toolbox probe` | 探测本机各 agent 已装能力 |
| `toolbox install <源> --as <id>` | 登记一个新工具 |

加 `--json` 得结构化输出。

### 统一调用契约

所有可执行工具都是同一条命令：

```bash
toolbox run <id> --in <输入路径> --out <输出路径> [--opt k=v ...] [-- 透传参数]
```

成功时 stdout 输出结果路径，失败时 stderr 输出人类可读原因，退出码非零。

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
  contract:
    input: PDF 文件路径
    output: CSV 文件路径
    limits: 扫描件不支持
  cost:
    install_minutes: 0
    smoke_test: "./adapter.sh --selftest"
  verified: true
  status: ok                  # ok | degraded | broken
  broken_reason: null
  added_at: 2026-11-02
```

`provides` 是**能力标签** —— 检索按标签匹配，不按名字匹配
（名字会变、作者会改名、能力不会）。

---

## 项目级叠加

项目可自带 `.workbuddy/toolbox/` 或 `.agent-toolbox/`，其中 `index.yaml` 与 `tools/`
与全局同构。

查找时**项目级优先**：项目里若有同 `id` 条目，直接遮蔽全局条目，
避免在项目特定语境下误用通用版。

---

## 原则与反模式

### 三态决策

| 态 | 含义 | 落地 |
|---|---|---|
| **复用** | 装入工具箱，任务中用 adapter 调用 | `tools/<id>/` |
| **借用** | 借鉴流程与结论，不直接调用代码 | `knowledge/<id>.md` |
| **自建** | 检索无解，自己写 | 留在项目里，不进 toolbox |

**「借用」不可省略。** 有些最好的成果不是代码，而是别人已验证过的流程设计。
只判"装"与"写"的二分，会把这整类高价值复用误判成不可用。

### 反模式（禁止）

1. **复现** — 重写一遍等于白烧 token
2. **过度适配** — 改 vendor 代码；适配写在 adapter 层
3. **索引污染** — 一次性东西塞进 toolbox；工具箱只收可复用的
4. **检索瘾** — 本地已有还在社区搜三小时；本地命中即止
5. **知识当代码** — 纯文档伪装成可执行工具；文档进 `knowledge/`

### 搜索预算

- 每环节最多 **4 次**检索调用
- 单任务跨环节合计 **≤ 12 次**
- 触顶即强制做决定；超预算继续时必须在产出中写明"此处未穷尽检索"

---

## 设计文档

- [先复用后自建 · 设计](docs/plans/2026-11-02-reuse-first-design.md)

---

## 许可

MIT
