"""toolbox CLI —— 先复用后自建。

跨 agent 通用：所有子命令都是纯 CLI，不依赖任何 agent 专属协议。
用法：
    toolbox list
    toolbox lookup <能力标签>
    toolbox run <id> --in <路径> --out <路径>        # 仅当条目声明了 --in/--out 契约
    toolbox run <id> -- <adapter 参数>              # 其余参数原样透传
    toolbox probe
    toolbox install <来源> --as <id>

调用契约的唯一真相是 index.yaml 里该条目的 entry.usage。
CLI 不得替工具编造接口 —— 编出来的提示会被直接照做，错一次就烧掉一轮。
"""

import argparse
import json
import os
import subprocess
import sys

HOME = os.path.expanduser("~")

# toolbox 仓库根目录：优先环境变量，其次默认位置
REPO_ROOT = os.environ.get("AGENT_TOOLBOX_HOME") or os.path.join(HOME, "agent-toolbox")

# 全局索引
GLOBAL_INDEX = os.path.join(REPO_ROOT, "index.yaml")
GLOBAL_TOOLS = os.path.join(REPO_ROOT, "tools")

# 项目级叠加目录（相对当前工作目录查找）
PROJECT_TOOLBOX_DIRS = [
    os.path.join(os.getcwd(), ".workbuddy", "toolbox"),
    os.path.join(os.getcwd(), ".agent-toolbox"),
]


def die(msg, code=1):
    print(msg, file=sys.stderr)
    sys.exit(code)


def read_index(path):
    """读取 index.yaml。极简 YAML 子集解析，零第三方依赖。

    支持的形态：
        key: value
        key:
          sub: value
        key:
          - item: {a: 1, b: 2}       # 行内字典
        key:
          - item:
              a: 1                   # 块字典
    索引文件由本 CLI 自己写入，格式受控，因此这个子集是够用的。
    """
    if not os.path.exists(path):
        return []
    lines = []
    with open(path, "r", encoding="utf-8") as f:
        for raw in f:
            if not raw.strip() or raw.strip().startswith("#"):
                continue
            indent = len(raw) - len(raw.lstrip(" "))
            lines.append((indent, raw.strip()))

    if not lines:
        return []

    data, _ = _parse_block(lines, 0, lines[0][0])
    if isinstance(data, dict):
        tools = data.get("tools")
        if isinstance(tools, list):
            return tools
        # 顶层直接是列表的情况
        return []
    if isinstance(data, list):
        return data
    return []


def _parse_block(lines, i, indent):
    """按缩进递归解析一个块，返回 (值, 下一个索引)。"""
    if lines[i][1].startswith("- "):
        return _parse_seq(lines, i, indent)
    return _parse_map(lines, i, indent)


def _parse_seq(lines, i, indent):
    out = []
    while i < len(lines) and lines[i][0] == indent and lines[i][1].startswith("- "):
        item_text = lines[i][1][2:].strip()
        i += 1
        item_indent = indent + 2
        item = {}
        if ":" in item_text:
            k, v = item_text.split(":", 1)
            k, v = k.strip(), v.strip()
            if v == "":
                if i < len(lines) and lines[i][0] > item_indent:
                    child, i = _parse_block(lines, i, lines[i][0])
                    item[k] = child
                else:
                    item[k] = None
            else:
                item[k] = _coerce(v)
        else:
            item = _coerce(item_text)

        # 该列表项自身的其余键，缩进为 item_indent
        while (i < len(lines) and lines[i][0] == item_indent
               and not lines[i][1].startswith("- ")):
            content = lines[i][1]
            if ":" not in content:
                i += 1
                continue
            k, v = content.split(":", 1)
            k, v = k.strip(), v.strip()
            i += 1
            if v == "":
                if i < len(lines) and lines[i][0] > item_indent:
                    child, i = _parse_block(lines, i, lines[i][0])
                    item[k] = child
                else:
                    item[k] = None
            else:
                item[k] = _coerce(v)
        out.append(item)
    return out, i


def _parse_map(lines, i, indent):
    out = {}
    while i < len(lines) and lines[i][0] == indent:
        content = lines[i][1]
        if content.startswith("- "):
            break
        if ":" not in content:
            i += 1
            continue
        k, v = content.split(":", 1)
        k, v = k.strip(), v.strip()
        i += 1
        if v == "":
            if i < len(lines) and lines[i][0] > indent:
                child, i = _parse_block(lines, i, lines[i][0])
                out[k] = child
            elif i < len(lines) and lines[i][0] == indent and lines[i][1].startswith("- "):
                child, i = _parse_seq(lines, i, indent)
                out[k] = child
            else:
                out[k] = None
        else:
            out[k] = _coerce(v)
    return out, i


def dump_yaml(obj, indent=0):
    """把 dict/list 序列化为本模块可读回的 YAML 子集。"""
    pad = " " * indent
    lines = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, (dict, list)) and v:
                lines.append(f"{pad}{k}:")
                lines.append(dump_yaml(v, indent + 2))
            elif isinstance(v, (dict, list)):
                lines.append(f"{pad}{k}: {'{}' if isinstance(v, dict) else '[]'}")
            else:
                lines.append(f"{pad}{k}: {_scalar(v)}")
    elif isinstance(obj, list):
        for item in obj:
            if isinstance(item, dict):
                body = dump_yaml(item, indent + 2)
                first, _, rest = body.partition("\n")
                lines.append(f"{pad}- {first.strip()}")
                if rest.strip():
                    lines.append(rest.rstrip("\n"))
            else:
                lines.append(f"{pad}- {_scalar(item)}")
    return "\n".join(lines)


def _scalar(v):
    if v is None:
        return "null"
    if v is True:
        return "true"
    if v is False:
        return "false"
    if isinstance(v, (int, float)):
        return str(v)
    s = str(v)
    if s == "":
        return '""'
    if any(c in s for c in ":#[]{},&*!|>'\"%@`") or s != s.strip():
        esc = s.replace("\\", "\\\\").replace('"', '\\"')
        return '"' + esc + '"'
    return s


def _coerce(v):
    """把 YAML 标量转成 Python 类型。"""
    if v in ("null", "~", ""):
        return None
    if v == "true":
        return True
    if v == "false":
        return False
    if v.startswith("[") and v.endswith("]"):
        inner = v[1:-1].strip()
        if not inner:
            return []
        return [_coerce(x.strip()) for x in inner.split(",")]
    if v.startswith("{") and v.endswith("}"):
        inner = v[1:-1].strip()
        out = {}
        if inner:
            for pair in inner.split(","):
                if ":" in pair:
                    k, val = pair.split(":", 1)
                    out[k.strip()] = _coerce(val.strip())
        return out
    if v.startswith('"') and v.endswith('"'):
        return v[1:-1].replace('\\"', '"').replace("\\\\", "\\")
    if v.startswith("'") and v.endswith("'"):
        return v[1:-1].replace("''", "'")
    if v.isdigit():
        return int(v)
    return v


def collect_entries():
    """收集两级索引。项目级同 id 遮蔽全局级。"""
    global_entries = read_index(GLOBAL_INDEX)
    merged = {}
    for e in global_entries:
        if e.get("id"):
            merged[e["id"]] = (e, "global")

    for d in PROJECT_TOOLBOX_DIRS:
        for e in read_index(os.path.join(d, "index.yaml")):
            if e.get("id"):
                merged[e["id"]] = (e, "project")

    return merged


def find_tool_dir(tool_id):
    """找到工具实际所在目录：项目级优先。"""
    for d in PROJECT_TOOLBOX_DIRS:
        p = os.path.join(d, "tools", tool_id)
        if os.path.isdir(p):
            return p
    p = os.path.join(GLOBAL_TOOLS, tool_id)
    if os.path.isdir(p):
        return p
    return None


def entry_form(tool_dir, meta):
    """条目到底能不能被 toolbox run —— 判据是入口文件本身，不是 kind 的名字。

    只按 kind == "executable" 分支踩过一次：把别人一整套 agent skill（入口是
    SKILL.md）登记进来后，lookup 仍然打出 "调用: toolbox run <id> <散文>"，
    而那条命令抄进终端必挂。CLI 不能替工具编造一个可执行面。

    返回 (形态, 入口绝对路径)：executable / document / missing / nowhere。
    """
    if tool_dir is None:
        return "nowhere", None
    cmd = meta.get("command") or "./adapter.sh"
    path = cmd if os.path.isabs(cmd) else os.path.join(tool_dir, cmd)
    if os.path.isfile(path):
        if os.access(path, os.X_OK):
            return "executable", path
        return "document", path
    return "missing", path


def rel_of(path):
    """相对仓库根的入口路径；path 可能为 None（条目在本机没有目录）。"""
    if not path:
        return "（本机无入口）"
    try:
        return os.path.relpath(path, REPO_ROOT)
    except ValueError:
        return path


# ---------------------------------------------------------------- list

def cmd_list(args):
    merged = collect_entries()
    if not merged:
        print("工具箱为空。")
        return
    rows = []
    for tid, (e, scope) in sorted(merged.items()):
        provides = e.get("provides") or []
        if isinstance(provides, str):
            provides = [provides]
        rows.append({
            "id": tid,
            "kind": e.get("kind", "?"),
            "scope": scope,
            "provides": provides,
            "status": e.get("status", "?"),
        })
    if args.json:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
        return
    print(f"{'ID':<28} {'KIND':<12} {'SCOPE':<8} {'STATUS':<10} PROVIDES")
    for r in rows:
        print(f"{r['id']:<28} {r['kind']:<12} {r['scope']:<8} {r['status']:<10} "
              f"{', '.join(r['provides'])}")


# ---------------------------------------------------------------- lookup

def cmd_lookup(args):
    merged = collect_entries()
    q = args.query.lower()
    hits = []
    for tid, (e, scope) in merged.items():
        blob = " ".join([
            tid,
            str(e.get("name", "")),
            str(e.get("kind", "")),
            str(e.get("status", "")),
            " ".join(e.get("provides") or []),
            str((e.get("contract") or {}).get("input", "")),
            str((e.get("contract") or {}).get("output", "")),
        ]).lower()
        if q in blob:
            hits.append((tid, e, scope))

    if args.json:
        print(json.dumps([
            {"id": t, "entry": e, "scope": s} for t, e, s in hits
        ], ensure_ascii=False, indent=2))
        return

    if not hits:
        print(f"未命中: {args.query}")
        print("提示: 换更宽的关键词，或该环节尚无现成工具 —— 可检索后装入。")
        return

    print(f"命中 {len(hits)} 条:\n")
    for tid, e, scope in hits:
        provides = e.get("provides") or []
        if isinstance(provides, str):
            provides = [provides]
        kind = e.get("kind", "?")
        status = e.get("status", "?")
        print(f"[{scope}] {tid}  ({kind}, {status})")
        if e.get("name"):
            print(f"  名称: {e['name']}")
        if provides:
            print(f"  能力: {', '.join(provides)}")

        entry = e.get("entry") or {}
        form, path = entry_form(find_tool_dir(tid), entry)

        # 调用方式只从条目声明里取。写死模板曾让 lookup 对一个只认
        # --text/--out 的工具打出 "--in/--out"，照提示调用必被 adapter 拒绝。
        # 而 kind 名也不能决定"能不能 run"：一整套 agent skill 的入口是 SKILL.md，
        # 拼出来的 "toolbox run <id> <散文>" 是一条跑不动的假命令。
        if kind == "knowledge":
            print(f"  取用: 读 knowledge/{tid}.md（知识条目不能 toolbox run）")
        elif form == "executable":
            if entry.get("usage"):
                print(f"  调用: toolbox run {tid} {entry['usage']}")
            else:
                print(f"  调用: toolbox run {tid} -- <adapter 参数>"
                      f"（条目未声明 entry.usage，先跑烟测看真实接口）")
        elif form == "document":
            print(f"  取用: 读 {rel_of(path)}，按其中的方法调用（入口不是可执行体，不能 toolbox run）")
            if entry.get("usage"):
                print(f"  用法: {entry['usage']}")
        elif form == "missing":
            print(f"  取用: ⚠️ 登记的入口 {entry.get('command') or './adapter.sh'} "
                  f"在 tools/{tid}/ 里不存在 —— 先重装或修正 entry.command")
        else:
            print(f"  取用: ⚠️ 索引有记录但本机没有 tools/{tid}/ 目录")

        src = e.get("source") or {}
        if src.get("license"):
            origin = f"  （来源 {src['url']}）" if src.get("url") else ""
            print(f"  许可: {src['license']}{origin}")

        if status == "needs_setup" or entry.get("setup"):
            print(f"  前置: {entry.get('setup') or f'未声明 setup，读 tools/{tid}/README.md'}")

        contract = e.get("contract") or {}
        if contract.get("input") or contract.get("output"):
            print(f"  契约: {contract.get('input', '?')} -> {contract.get('output', '?')}")
        if contract.get("limits"):
            print(f"  限制: {contract['limits']}")

        cost = e.get("cost") or {}
        if cost.get("smoke_test"):
            # 分支逐个判，别用字典字面量：字面量会把所有值都算一遍，
            # 于是 path 为 None 的条目（索引有记录、本机没目录）当场 TypeError。
            if kind == "knowledge":
                where = "知识条目：回原项目复核，toolbox 目录里没有可执行体"
            elif form == "executable":
                where = f"在 tools/{tid}/ 目录内执行"
            elif form == "document":
                where = f"按 {rel_of(path)} 的流程真跑一遍到出产物"
            elif form == "missing":
                where = "入口缺失，先补装再谈烟测"
            else:
                where = "本机没有该工具目录，先装"
            print(f"  烟测: {cost['smoke_test']}  （{where}）")
        when = e.get("verified_at") or e.get("added_at") or "?"
        if e.get("verified"):
            meaning = ("登记时烟测真跑通" if form == "executable"
                       else "该流程/结论在真实任务里走过一遍")
            print(f"  验证: {meaning} @ {when} —— 只说明当时成立，换环境需复核")
        else:
            print("  验证: 未实测 —— 用之前必须先烟测，别把索引里的描述当证据")
        if e.get("broken_reason"):
            print(f"  已损坏: {e['broken_reason']}")
        print()


# ---------------------------------------------------------------- run

def cmd_run(args):
    merged = collect_entries()
    if args.id not in merged:
        die(f"未找到工具: {args.id}\n提示: toolbox lookup <能力标签> 查看可用工具")

    entry, scope = merged[args.id]
    if entry.get("status") == "broken":
        die(f"工具 {args.id} 已标记为 broken: {entry.get('broken_reason', '未知')}")
    if entry.get("status") == "needs_setup":
        setup = (entry.get("entry") or {}).get("setup") or "读 tools/%s/README.md" % args.id
        print(f"⚠️  {args.id} 标记为 needs_setup，本机前置未就绪。\n"
              f"   先执行: {setup}\n"
              f"   （仍尝试运行，失败请把 status 保持 needs_setup 直到烟测过）",
              file=sys.stderr)
    if entry.get("status") == "unavailable":
        die(f"工具 {args.id} 当前不可用（来源不可达/装不上）: "
            f"{entry.get('broken_reason', '未记录原因')}")

    tool_dir = find_tool_dir(args.id)
    if tool_dir is None:
        die(f"索引有记录但找不到工具目录: {args.id}")

    meta = entry.get("entry") or {}
    cmd = meta.get("command") or "./adapter.sh"

    form, path = entry_form(tool_dir, meta)
    if form != "executable":
        rel = path or os.path.join(tool_dir, cmd)
        die(f"{args.id} 不能 toolbox run —— 入口 {rel} 不是可执行体（形态: {form}）。\n"
            f"这类条目是别人的一整套方法/文档，按它自己的流程调用；"
            f"取法见: toolbox lookup {args.id}")

    argv = [cmd]
    argv.extend(meta.get("args") or [])
    if args.inp:
        argv.extend(["--in", args.inp])
    if args.out:
        argv.extend(["--out", args.out])
    for opt in args.opt or []:
        if "=" not in opt:
            die(f"--opt 需要 key=value 形式: {opt}")
        argv.append(opt)

    # -- 之后的参数原样透传
    rest = list(args.rest or [])
    if rest and rest[0] == "--":
        rest = rest[1:]
    argv.extend(rest)

    # 展开 {input} / {output} 占位符
    argv = [a.replace("{input}", args.inp or "").replace("{output}", args.out or "")
            for a in argv]

    print(f"运行 {args.id}: {argv[0]} {' '.join(argv[1:])}", file=sys.stderr)
    try:
        proc = subprocess.run(argv, cwd=tool_dir, shell=False)
    except FileNotFoundError:
        die(f"入口不存在: {argv[0]}")
    except PermissionError:
        die(f"入口不可执行: {argv[0]}")
    sys.exit(proc.returncode)


# ---------------------------------------------------------------- probe

AGENT_PROBE_DIRS = [
    ("claude-code", os.path.join(HOME, ".claude", "skills")),
    ("codex", os.path.join(HOME, ".codex", "skills")),
    ("workbuddy", os.path.join(HOME, ".workbuddy", "skills")),
    ("gemini", os.path.join(HOME, ".gemini", "skills")),
    ("opencode", os.path.join(HOME, ".config", "opencode", "skills")),
    ("agents-shared", os.path.join(HOME, ".agents", "skills")),
]

MCP_PROBE_FILES = [
    ("claude-code", os.path.join(HOME, ".claude", ".mcp.json")),
    ("codex", os.path.join(HOME, ".codex", "config.toml")),
    ("workbuddy", os.path.join(HOME, ".workbuddy", "mcp.json")),
]


# ---------------------------------------------------------------- budget

BUDGET_FILE = os.path.join(REPO_ROOT, ".budget.json")

# 两本账分开记：检索（找候选）与验证（跑通候选）是两种成本。
# 混在一起会让"实测淘汰 5 个配音引擎"这种必要的验证，
# 读起来像检索失控 —— 于是记录者开始谎报用量，预算机制就废了。
BUDGET_LIMITS = {
    "retrieve": {"segment": 4, "task": 12, "label": "检索"},
    "verify": {"segment": 3, "task": 8, "label": "验证"},
}


def _load_budget():
    if not os.path.exists(BUDGET_FILE):
        return _new_budget(None)
    try:
        with open(BUDGET_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return _new_budget(None)
    return _normalize_budget(data)


def _new_budget(task):
    return {"task": task, "kinds": {k: {"segments": {}, "total": 0}
                                    for k in BUDGET_LIMITS}}


def _normalize_budget(data):
    """兼容旧格式（顶层 segments/total 且不分账）。"""
    if "kinds" not in data:
        legacy = {"segments": data.get("segments", {}),
                  "total": data.get("total", 0)}
        data = {"task": data.get("task"),
                "kinds": {"retrieve": legacy,
                          "verify": {"segments": {}, "total": 0}}}
    for k in BUDGET_LIMITS:
        data["kinds"].setdefault(k, {"segments": {}, "total": 0})
    return data


def _save_budget(data):
    with open(BUDGET_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def cmd_budget(args):
    """预算计数。让「超预算」变成机制能发现的事，而非靠自觉。

    用法：
        toolbox budget --reset --task <任务名>
        toolbox budget --spend --segment <环节名> [--kind retrieve|verify]
        toolbox budget                      查两本账的用量
    """
    data = _normalize_budget(_load_budget())

    if args.reset:
        data = _new_budget(args.task or "untitled")
        _save_budget(data)
        print(f"预算已重置: task={data['task']}")
        return

    kind = args.kind or "retrieve"
    if kind not in BUDGET_LIMITS:
        die(f"--kind 只支持 {', '.join(BUDGET_LIMITS)}")
    limits = BUDGET_LIMITS[kind]
    label = limits["label"]

    if args.spend:
        bucket = data["kinds"][kind]
        seg = args.segment or "default"
        bucket["segments"][seg] = bucket["segments"].get(seg, 0) + 1
        bucket["total"] = bucket.get("total", 0) + 1
        _save_budget(data)
        seg_used = bucket["segments"][seg]
        over_seg = seg_used > limits["segment"]
        over_task = bucket["total"] > limits["task"]
        print(f"{label}调用: 环节[{seg}] {seg_used}/{limits['segment']}  "
              f"任务合计 {bucket['total']}/{limits['task']}")
        if over_seg or over_task:
            print(file=sys.stderr)
            print(f"⚠️  {label}预算已超限。必须停止{label}并做决定：", file=sys.stderr)
            if kind == "retrieve":
                print("     装冠军 / 借用 / 标杆复刻 / 自建 / 放弃优化该环节", file=sys.stderr)
                print("     若仍要继续，在最终产出中写明「此处未穷尽检索」。",
                      file=sys.stderr)
            else:
                print("     选定冠军并停止继续验证；未验证到的部分标 verified: false",
                      file=sys.stderr)
                print("     若仍要继续，在最终产出中写明「此处未验证到 L3」。",
                      file=sys.stderr)
            sys.exit(3)
        return

    # status
    print(f"任务: {data.get('task') or '(未开始)'}")
    for k, lim in BUDGET_LIMITS.items():
        bucket = data["kinds"][k]
        print(f"{lim['label']}: 合计 {bucket.get('total', 0)}/{lim['task']}")
        for seg, n in sorted(bucket.get("segments", {}).items(),
                             key=lambda kv: -kv[1]):
            flag = " ⚠️超限" if n > lim["segment"] else ""
            print(f"  {seg}: {n}/{lim['segment']}{flag}")


def cmd_probe(args):
    """探测本机各 agent 已装能力。这是跨 agent 的关键：skill 层不含路径，
    全部由 CLI 代劳。"""
    result = {"skills": {}, "mcp": {}, "toolbox": {}}

    for name, d in AGENT_PROBE_DIRS:
        if os.path.isdir(d):
            try:
                names = sorted(x for x in os.listdir(d)
                               if not x.startswith("."))
            except OSError:
                names = []
            result["skills"][name] = {"path": d, "count": len(names),
                                      "items": names[:200]}

    for name, f in MCP_PROBE_FILES:
        if os.path.exists(f):
            try:
                with open(f, "r", encoding="utf-8") as fh:
                    content = fh.read()
                if f.endswith(".json"):
                    data = json.loads(content)
                    servers = list((data.get("mcpServers") or {}).keys())
                else:
                    servers = [ln.strip() for ln in content.splitlines()
                               if ln.strip().startswith("[") and "." in ln]
                result["mcp"][name] = {"path": f, "servers": servers}
            except (OSError, ValueError):
                result["mcp"][name] = {"path": f, "servers": []}

    merged = collect_entries()
    result["toolbox"] = {tid: {"scope": s, "status": e.get("status", "?")}
                         for tid, (e, s) in merged.items()}

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    print("已装 skill:")
    for name, info in result["skills"].items():
        print(f"  {name:<16} {info['count']:>4} 个  {info['path']}")
    print("\n已配 MCP:")
    for name, info in result["mcp"].items():
        print(f"  {name:<16} {len(info['servers']):>4} 个  {info['path']}")
        for s in info["servers"][:20]:
            print(f"      - {s}")
    print(f"\n工具箱: {len(merged)} 个工具")


# ---------------------------------------------------------------- install

def cmd_install(args):
    """登记一个新工具。此处只做登记与放置，实际下载由 agent 按来源说明执行，
    这样避免在 CLI 里绑死某个包管理器的假设。"""
    tool_id = args.as_id
    if not tool_id:
        die("必须用 --as <id> 指定工具 id")

    tool_dir = os.path.join(GLOBAL_TOOLS, tool_id)
    if os.path.exists(tool_dir) and not args.force:
        die(f"工具已存在: {tool_id}（--force 可覆盖）")

    os.makedirs(tool_dir, exist_ok=True)

    entry = {
        "id": tool_id,
        "name": args.name or tool_id,
        "kind": args.kind,
        "provides": args.provides or [],
        "source": {"type": args.source, "url": args.url or ""},
        "entry": {"command": "./adapter.sh", "args": [],
                  "usage": "", "setup": ""},
        "status": "needs_setup",
        "verified": False,
        "added_at": _today(),
    }

    merged = collect_entries()
    merged[tool_id] = (entry, "global")
    _write_index(GLOBAL_INDEX, list(merged.values()))

    print(f"已登记: {tool_id}")
    print(f"工具目录: {tool_dir}")
    print("下一步: 放置 vendor 代码、编写 adapter.sh，并补全 index.yaml：")
    print("  entry.usage —— adapter 真正接受的参数形状（lookup 会原样转告，不许猜）")
    print("  entry.setup + status —— 前置准备命令；没跑通前置之前 status 保持 needs_setup")
    print("  contract + cost.smoke_test + verified/verified_at —— 跑过才填 true")


def _write_index(path, entries):
    """写出 index.yaml，保留注释头（含字段约定，供人和 agent 对照）。"""
    header = [
        "# 工具箱索引 —— 由 toolbox CLI 维护，也可手工编辑。",
        "# provides 是能力标签，检索按标签匹配，不按名字匹配。",
        "#",
        "# 字段约定（lookup 会原样转告；写错就等于对下一个使用者撒谎）：",
        "#   entry.usage   该工具真实接受的参数形状。不填时 lookup 只说\"未声明\"，不再编模板",
        "#   entry.setup   前置准备命令（建 venv、下模型等）",
        "#   status        ok=现在能跑 / needs_setup=代码在位但前置未就绪",
        "#                 unavailable=来源不可达或装不上（写明恢复条件）/ broken=实测跑不通",
        "#   verified      true 仅表示\"登记时 smoke_test 真跑通过\"，配 verified_at；",
        "#                 它不代表换一台机器、换一个 venv 还能跑",
        "#",
        "# tools:",
    ]
    body = dump_yaml({"tools": [e for e, _ in entries]}, 0)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(header) + "\n")
        f.write(body + "\n")


def _today():
    import datetime
    return datetime.date.today().isoformat()


# ---------------------------------------------------------------- main

def main():
    # --json 挂在每个子命令上，而不是只挂根解析器：
    # `toolbox lookup x --json` 是最自然的写法，若只支持 `toolbox --json lookup x`，
    # README 里那句"加 --json 得结构化输出"就会在真实调用顺序上直接报错。
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--json", action="store_true", default=argparse.SUPPRESS,
                        help="以 JSON 输出")

    p = argparse.ArgumentParser(prog="toolbox", description="先复用后自建：工具箱 CLI")
    p.add_argument("--json", action="store_true", help="以 JSON 输出")
    sub = p.add_subparsers(dest="cmd")

    sp = sub.add_parser("list", parents=[common], help="列出全部工具")
    sp.set_defaults(func=cmd_list)

    sp = sub.add_parser("lookup", parents=[common], help="按能力标签查找工具")
    sp.add_argument("query")
    sp.set_defaults(func=cmd_lookup)

    sp = sub.add_parser("run", help="调用一个工具（参数形状见 lookup 打印的「调用:」行）")
    sp.add_argument("id")
    sp.add_argument("--in", dest="inp")
    sp.add_argument("--out", dest="out")
    sp.add_argument("--opt", action="append")
    sp.add_argument("rest", nargs=argparse.REMAINDER,
                    help="-- 之后的参数原样透传给 adapter")
    sp.set_defaults(func=cmd_run)

    sp = sub.add_parser("probe", parents=[common], help="探测本机各 agent 已装能力")
    sp.set_defaults(func=cmd_probe)

    sp = sub.add_parser("budget", help="预算计数（检索 / 验证 分两本账）")
    sp.add_argument("--reset", action="store_true", help="重置预算")
    sp.add_argument("--task", help="任务名（配合 --reset）")
    sp.add_argument("--spend", action="store_true", help="记一次调用")
    sp.add_argument("--kind", default="retrieve", choices=sorted(BUDGET_LIMITS),
                    help="retrieve=找候选的检索，verify=跑通候选的验证")
    sp.add_argument("--segment", help="环节名（配合 --spend）")
    sp.set_defaults(func=cmd_budget)

    sp = sub.add_parser("install", help="登记一个新工具")
    sp.add_argument("source")
    sp.add_argument("--as", dest="as_id")
    sp.add_argument("--name")
    sp.add_argument("--kind", default="executable",
                    choices=["executable", "knowledge"])
    sp.add_argument("--provides", nargs="*")
    sp.add_argument("--url")
    sp.add_argument("--force", action="store_true")
    sp.set_defaults(func=cmd_install)

    args = p.parse_args()
    if not getattr(args, "func", None):
        p.print_help()
        sys.exit(0)
    args.func(args)


if __name__ == "__main__":
    main()
