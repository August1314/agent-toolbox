#!/usr/bin/env bash
# adapter.sh —— pdf-table-extract 的薄适配层
#
# 契约：toolbox run pdf-table-extract --in <pdf> --out <csv>
# 职责：仅做参数映射与输出约定。业务逻辑全部在 vendor/ 里。
#
# vendor 原样，不修改。升级上游时直接替换 vendor/ 即可，本文件不动。

set -euo pipefail

IN=""
OUT=""
SELFTEST=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --in) IN="$2"; shift 2 ;;
    --out) OUT="$2"; shift 2 ;;
    --selftest) SELFTEST=1; shift ;;
    *) echo "未知参数: $1" >&2; exit 2 ;;
  esac
done

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENDOR="${HERE}/vendor"

if [[ $SELFTEST -eq 1 ]]; then
  # 烟测：生成一个最小 PDF，确认能提取出表头
  tmp="$(mktemp -d)"
  trap 'rm -rf "${tmp}"' EXIT
  python3 "${VENDOR}/extract.py" --selftest --out "${tmp}/out.csv"
  [[ -s "${tmp}/out.csv" ]] || { echo "烟测失败：输出为空" >&2; exit 1; }
  echo "烟测通过: $(head -1 "${tmp}/out.csv")"
  exit 0
fi

if [[ -z "${IN}" || -z "${OUT}" ]]; then
  echo "用法: toolbox run pdf-table-extract --in <pdf> --out <csv>" >&2
  exit 2
fi

[[ -f "${IN}" ]] || { echo "输入文件不存在: ${IN}" >&2; exit 1; }

python3 "${VENDOR}/extract.py" --in "${IN}" --out "${OUT}"
echo "${OUT}"
