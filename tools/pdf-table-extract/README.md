# pdf-table-extract

PDF 表格提取 —— 保留表头与列结构，输出 CSV。

## 来源

- type: github（本地 vendor 实现，MIT）
- license: MIT
- 说明：`vendor/extract.py` 为纯标准库实现，不依赖 pdfplumber / pypdf。
  若后续要换更强的上游实现（pdfplumber 等），整体替换 `vendor/` 目录即可，
  `adapter.sh` 无需改动。

## 调用

```bash
toolbox run pdf-table-extract --in input.pdf --out table.csv
```

烟测：

```bash
toolbox run pdf-table-extract --selftest
```

## 契约

- **输入**：PDF 文件路径
- **输出**：CSV 文件路径（列宽按最长行对齐，不足处补空）
- **限制**：
  - 扫描件（图片型 PDF）不支持 —— 无文本层
  - 纯文本流可读出内容，但**视觉上的合并单元格无法还原**，
    本实现不做猜测填充（避免编造数据）
  - 单文件建议 < 50MB

## 何时用

需要把 PDF 里的表格变成结构化数据时。先 `toolbox lookup pdf table extract` 确认是否已有更优候选，
若本条不合适，可直接在索引里换 id 重装。

## 已知限制与后续

- 若发现某类 PDF 抽取效果不好，记录在索引条目的 `broken_reason` 或 README 的
  「待改进」段，避免下次重复踩坑。
