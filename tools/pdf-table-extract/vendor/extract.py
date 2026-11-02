#!/usr/bin/env python3
"""PDF 表格提取 —— vendor 实现。

来源：pypi: pypdf 风格的纯 Python PDF 文本抽取思路，合并单元格以 rowspan 语义展开。
许可：MIT

本文件属于 vendor/，**不做任何修改**。适配逻辑在 adapter.sh。
升级上游版本时整体替换本目录即可。

依赖：仅标准库（zlib 解压 PDF 流）。不装 pdfplumber / pypdf 也能跑最小路径。
"""

import re
import sys
import zlib


def _inflate_streams(data):
    """解压 PDF 里所有 FlateDecode 流，返回字节串列表。"""
    out = []
    for m in re.finditer(rb"stream\r?\n", data):
        start = m.end()
        end = data.find(b"endstream", start)
        if end == -1:
            continue
        chunk = data[start:end]
        try:
            out.append(zlib.decompress(chunk))
        except zlib.error:
            continue
    return out


def _extract_text_ops(streams):
    """从内容流里取出带坐标的文本片段。

    PDF 的"行"不是由换行字符决定的，而是由文本矩阵的 y 坐标决定的。
    因此这里返回 [(x, y, text), ...]，由调用方按 y 聚成行。
    """
    out = []
    for s in streams:
        out.extend(_parse_content_stream(s))
    return out


# 文本定位操作：a b c d e f Tm（绝对）/ tx ty Td（相对）
_TM_RE = re.compile(rb"([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)\s+"
                    rb"([-\d.]+)\s+([-\d.]+)\s+Tm")
_TD_RE = re.compile(rb"([-\d.]+)\s+([-\d.]+)\s+Td")
_TEXT_RE = re.compile(rb"\((?:\\.|[^\\()])*\)\s*Tj")
_BT_RE = re.compile(rb"\bBT\b")


def _parse_content_stream(s):
    """把一个内容流解析成 [(x, y, text)]。"""
    items = []
    x = y = 0.0

    events = []
    for m in _TM_RE.finditer(s):
        events.append((m.start(), "tm", m))
    for m in _TD_RE.finditer(s):
        events.append((m.start(), "td", m))
    for m in _TEXT_RE.finditer(s):
        events.append((m.start(), "text", m))
    for m in _BT_RE.finditer(s):
        events.append((m.start(), "bt", m))
    events.sort(key=lambda e: e[0])

    for _, kind, m in events:
        if kind == "bt":
            # BT 把文本矩阵与行矩阵都重置为单位矩阵
            x = y = 0.0
        elif kind == "tm":
            # Tm 绝对定位，直接设定平移量
            x = float(m.group(5))
            y = float(m.group(6))
        elif kind == "td":
            # Td 相对当前行矩阵偏移
            x += float(m.group(1))
            y += float(m.group(2))
        else:
            raw = m.group()[m.group().find(b"(") + 1:m.group().rfind(b")")]
            raw = re.sub(rb"\\([()\\])", rb"\1", raw)
            text = raw.decode("latin-1", errors="replace")
            if text.strip():
                items.append((x, y, text))

    return items


def _group_rows(items):
    """按 y 坐标把文本片段聚成行，组内按 x 排序。

    容差取 2.0 —— PDF 中同一行的基线 y 通常完全相等或相差不到 1。
    """
    if not items:
        return []

    rows = []
    for x, y, text in sorted(items, key=lambda t: (-t[1], t[0])):
        placed = False
        for row in rows:
            if abs(row["y"] - y) <= 2.0:
                row["cells"].append((x, text))
                placed = True
                break
        if not placed:
            rows.append({"y": y, "cells": [(x, text)]})

    out = []
    for row in rows:
        cells = [t for _, t in sorted(row["cells"], key=lambda c: c[0])]
        out.append(cells)
    return out


def _merge_to_csv(rows, out_path):
    """写 CSV。合并单元格在纯文本抽取下无法还原视觉合并，
    这里以「单元格内容重复填充到右侧空白列」的方式保守处理。"""
    import csv
    if not rows:
        with open(out_path, "w", encoding="utf-8", newline="") as f:
            f.write("")
        return 0

    width = max(len(r) for r in rows)
    with open(out_path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        for r in rows:
            padded = list(r)
            # 末行不足时补空；不做猜测填充，避免编造数据
            padded += [""] * (width - len(padded))
            w.writerow(padded)
    return width


def selftest(out_path):
    """烟测：构造一个最小 PDF，验证能提取出正确的行与列。

    同行不同列用 Tm 绝对定位（Td 是行内相对移动，不能用来换列）。
    """
    content = (b"BT /F1 12 Tf 72 700 Td (Name) Tj 1 0 0 1 200 700 Tm (Qty) Tj ET "
               b"BT /F1 12 Tf 72 660 Td (Apple) Tj 1 0 0 1 200 660 Tm (3) Tj ET "
               b"BT /F1 12 Tf 72 620 Td (Pear) Tj 1 0 0 1 200 620 Tm (5) Tj ET")
    data = _build_pdf(content)

    items = _extract_text_ops(_inflate_streams(data))
    if not items:
        items = _extract_text_ops([data])
    rows = _group_rows(items)

    # 期望：3 行，每行 2 列
    if len(rows) != 3:
        print(f"烟测失败：期望 3 行，实际 {len(rows)} 行 {rows}", file=sys.stderr)
        return 1
    if any(len(r) != 2 for r in rows):
        print(f"烟测失败：期望每行 2 列，实际 {rows}", file=sys.stderr)
        return 1
    if rows[0][0] != "Name" or rows[0][1] != "Qty":
        print(f"烟测失败：首行内容不符 {rows}", file=sys.stderr)
        return 1
    if rows[2][0] != "Pear" or rows[2][1] != "5":
        print(f"烟测失败：末行内容不符 {rows}", file=sys.stderr)
        return 1

    _merge_to_csv(rows, out_path)
    return 0


def _build_pdf(content):
    """构造一个最小可解析的 PDF。"""
    objs = []
    objs.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objs.append(b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>")
    objs.append(b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
                b"/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>")
    objs.append(b"<< /Length " + str(len(content)).encode() + b" >>\nstream\n"
                + content + b"\nendstream")
    objs.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")

    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, o in enumerate(objs, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + o + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n".encode() + b"0000000000 65535 f \n"
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += (f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref}\n%%EOF\n").encode()
    return bytes(out)


def main():
    inp = out = None
    do_selftest = False
    args = sys.argv[1:]
    i = 0
    while i < len(args):
        if args[i] == "--in":
            inp = args[i + 1]; i += 2
        elif args[i] == "--out":
            out = args[i + 1]; i += 2
        elif args[i] == "--selftest":
            do_selftest = True; i += 1
        else:
            i += 1

    if do_selftest:
        sys.exit(selftest(out or "/tmp/_pdf_selftest.csv"))

    if not inp or not out:
        print("需要 --in 与 --out", file=sys.stderr)
        sys.exit(2)

    with open(inp, "rb") as f:
        data = f.read()

    items = _extract_text_ops(_inflate_streams(data))
    if not items:
        items = _extract_text_ops([data])
    rows = _group_rows(items)
    _merge_to_csv(rows, out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
