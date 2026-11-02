"""toolbox CLI —— 先复用后自建。

跨 agent 通用：所有子命令都是纯 CLI，不依赖任何 agent 专属协议。
用法：
    toolbox list
    toolbox lookup <能力标签>
    toolbox run <id> --in <路径> --out <路径> [--opt k=v ...]
    toolbox probe
    toolbox install <来源> --as <id>
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
        return '"' + s.replace('"', '\\"') + '"'
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
    if (v.startswith('"') and v.endswith('"')) or (v.startswith("'") and v.endswith("'")):
        return v[1:-1]
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
        print(f"[{scope}] {tid}  ({e.get('kind', '?')}, {e.get('status', '?')})")
        if e.get("name"):
            print(f"  名称: {e['name']}")
        if provides:
            print(f"  能力: {', '.join(provides)}")
        entry = e.get("entry") or {}
        if entry.get("command"):
            print(f"  调用: toolbox run {tid} --in <输入> --out <输出>")
        contract = e.get("contract") or {}
        if contract.get("input") or contract.get("output"):
            print(f"  契约: {contract.get('input', '?')} -> {contract.get('output', '?')}")
        if contract.get("limits"):
            print(f"  限制: {contract['limits']}")
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

    tool_dir = find_tool_dir(args.id)
    if tool_dir is None:
        die(f"索引有记录但找不到工具目录: {args.id}")

    meta = entry.get("entry") or {}
    cmd = meta.get("command") or "./adapter.sh"

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
PER_SEGMENT_LIMIT = 4
PER_TASK_LIMIT = 12


def _load_budget():
    if not os.path.exists(BUDGET_FILE):
        return {"task": None, "segments": {}, "total": 0}
    try:
        with open(BUDGET_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {"task": None, "segments": {}, "total": 0}


def _save_budget(data):
    with open(BUDGET_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def cmd_budget(args):
    """搜索预算计数。让「超预算」变成机制能发现的事，而非靠自觉。

    用法：
        toolbox budget reset --task <任务名>       开始一个新任务
        toolbox budget spend --segment <环节名>   记一次检索调用
        toolbox budget status                     查当前用量
    """
    data = _load_budget()

    if args.reset:
        data = {"task": args.task or "untitled", "segments": {}, "total": 0}
        _save_budget(data)
        print(f"预算已重置: task={data['task']}")
        return

    if args.spend:
        seg = args.segment or "default"
        data["segments"][seg] = data["segments"].get(seg, 0) + 1
        data["total"] = data.get("total", 0) + 1
        _save_budget(data)
        seg_used = data["segments"][seg]
        over_seg = seg_used > PER_SEGMENT_LIMIT
        over_task = data["total"] > PER_TASK_LIMIT
        print(f"检索调用: 环节[{seg}] {seg_used}/{PER_SEGMENT_LIMIT}  "
              f"任务合计 {data['total']}/{PER_TASK_LIMIT}")
        if over_seg or over_task:
            print(file=sys.stderr)
            print("⚠️  预算已超限。必须停止检索并做决定：", file=sys.stderr)
            print("     装冠军 / 借用 / 自建 / 放弃优化该环节", file=sys.stderr)
            print("     若仍要继续，在最终产出中写明「此处未穷尽检索」。",
                  file=sys.stderr)
            sys.exit(3)
        return

    # status
    print(f"任务: {data.get('task') or '(未开始)'}")
    print(f"总计: {data.get('total', 0)}/{PER_TASK_LIMIT}")
    for seg, n in sorted(data.get("segments", {}).items(),
                         key=lambda kv: -kv[1]):
        flag = " ⚠️超限" if n > PER_SEGMENT_LIMIT else ""
        print(f"  {seg}: {n}/{PER_SEGMENT_LIMIT}{flag}")


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
        "status": "ok",
        "verified": False,
        "added_at": _today(),
    }

    merged = collect_entries()
    merged[tool_id] = (entry, "global")
    _write_index(GLOBAL_INDEX, list(merged.values()))

    print(f"已登记: {tool_id}")
    print(f"工具目录: {tool_dir}")
    print("下一步: 放置 vendor 代码、编写 adapter.sh、补全 index.yaml 的 contract 字段")


def _write_index(path, entries):
    """写出 index.yaml，保留原有注释头。"""
    header = [
        "# 工具箱索引 —— 由 toolbox CLI 维护，也可手工编辑。",
        "# provides 是能力标签，检索按标签匹配，不按名字匹配。",
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
    p = argparse.ArgumentParser(prog="toolbox", description="先复用后自建：工具箱 CLI")
    p.add_argument("--json", action="store_true", help="以 JSON 输出")
    sub = p.add_subparsers(dest="cmd")

    sp = sub.add_parser("list", help="列出全部工具")
    sp.set_defaults(func=cmd_list)

    sp = sub.add_parser("lookup", help="按能力标签查找工具")
    sp.add_argument("query")
    sp.set_defaults(func=cmd_lookup)

    sp = sub.add_parser("run", help="调用一个工具")
    sp.add_argument("id")
    sp.add_argument("--in", dest="inp")
    sp.add_argument("--out", dest="out")
    sp.add_argument("--opt", action="append")
    sp.add_argument("rest", nargs=argparse.REMAINDER,
                    help="-- 之后的参数原样透传给 adapter")
    sp.set_defaults(func=cmd_run)

    sp = sub.add_parser("probe", help="探测本机各 agent 已装能力")
    sp.set_defaults(func=cmd_probe)

    sp = sub.add_parser("budget", help="搜索预算计数")
    sp.add_argument("--reset", action="store_true", help="重置预算")
    sp.add_argument("--task", help="任务名（配合 --reset）")
    sp.add_argument("--spend", action="store_true", help="记一次检索调用")
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
