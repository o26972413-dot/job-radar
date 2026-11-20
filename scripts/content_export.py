#!/usr/bin/env python3
"""内容选题专用导出器 —— 从 job-radar 的 jobs.json 导出每日全部新增。

与官方 notify_preview.py 的区别：
  - 官方：只筛「27届 + 产品/数据方向 + 高分」，是个人求职精准推荐
  - 本脚本：导出当天 first_seen 的全部新增，不限届别/方向，面向内容选题「数据尽量全」

输出：
  data/content_digest/YYYY-MM-DD.csv   —— 全字段表格，可导 Excel / 数据分析
  data/content_digest/YYYY-MM-DD.md    —— 按公司分组的选题清单，可直接看
  data/content_digest/YYYY-MM-DD.json  —— 原始结构化数据

用法：
  python scripts/content_export.py            # 导出最新 first_seen 日期的新增
  python scripts/content_export.py 2026-11-20 # 指定日期
  python scripts/content_export.py --all      # 导出当前全量在架岗位
"""
from __future__ import annotations

import csv
import datetime as dt
import json
import os
import sys
from collections import Counter

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JOBS = os.path.join(BASE, "data", "jobs.json")
OUT_DIR = os.path.join(BASE, "data", "content_digest")

# CSV 列：内容选题最需要的字段在前
COLUMNS = [
    ("company_name", "公司"),
    ("title", "岗位名称"),
    ("location", "城市"),
    ("org_type", "机构类型"),
    ("industry", "行业"),
    ("role_primary", "方向"),
    ("publish_time", "发布时间"),
    ("deadline", "截止日期"),
    ("first_seen", "首次发现"),
    ("source_id", "信源"),
    ("match_score", "匹配分"),
    ("tags", "标签"),
    ("official_url", "投递链接"),
    ("jd_text", "JD摘要"),
]


def norm(v):
    if v is None:
        return ""
    if isinstance(v, (list, tuple)):
        return "/".join(str(x) for x in v)
    if isinstance(v, str):
        return v.replace("\n", " ").strip()
    return str(v)


def pick(job: dict) -> dict:
    row = {}
    for key, _ in COLUMNS:
        v = job.get(key, "")
        if key == "jd_text":
            v = norm(v)[:300]  # JD 截断，避免 CSV 单元格过长
        elif key == "role_primary":
            v = norm(job.get("role_primary") or job.get("primary_role") or "")
        else:
            v = norm(v)
        row[key] = v
    return row


def export(rows: list[dict], label: str) -> None:
    os.makedirs(OUT_DIR, exist_ok=True)
    csv_path = os.path.join(OUT_DIR, f"{label}.csv")
    md_path = os.path.join(OUT_DIR, f"{label}.md")
    json_path = os.path.join(OUT_DIR, f"{label}.json")

    with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow([cn for _, cn in COLUMNS])
        for j in rows:
            r = pick(j)
            w.writerow([r[k] for k, _ in COLUMNS])

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=1)

    by_company = Counter(j.get("company_name", "未知") for j in rows)
    lines = [
        f"# 校招新增选题清单 · {label}",
        "",
        f"共 **{len(rows)}** 条新增，来自 **{len(by_company)}** 家公司。",
        "",
        "## 公司分布",
        "",
        "| 公司 | 新增岗位数 |",
        "|---|---:|",
    ]
    for comp, c in by_company.most_common():
        lines.append(f"| {comp} | {c} |")
    lines += ["", "## 全部新增岗位", ""]
    last_company = None
    for j in sorted(rows, key=lambda x: (x.get("company_name", ""), x.get("title", ""))):
        comp = j.get("company_name", "未知")
        if comp != last_company:
            lines += [f"### {comp}", ""]
            last_company = comp
        title = norm(j.get("title"))
        loc = norm(j.get("location"))
        url = norm(j.get("official_url"))
        tags = "/".join(j.get("tags", [])[:5]) if isinstance(j.get("tags"), list) else norm(j.get("tags"))
        lines.append(f"- **{title}**｜{loc}" + (f"｜{tags}" if tags else "") + (f"｜[投递]({url})" if url else ""))
    lines.append("")

    with open(md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print(f"✅ 导出 {len(rows)} 条 → {OUT_DIR}")
    print(f"   CSV: {csv_path}")
    print(f"   MD : {md_path}")
    print(f"   JSON:{json_path}")


def main():
    args = sys.argv[1:]
    all_mode = "--all" in args
    args = [a for a in args if a != "--all"]

    jobs = json.load(open(JOBS, encoding="utf-8"))
    active = [j for j in jobs if not j.get("gone")]

    if all_mode:
        label = dt.date.today().isoformat() + "-全量"
        rows = active
    else:
        if args:
            label = args[0]
        else:
            days = sorted({(j.get("first_seen") or "")[:10] for j in active if j.get("first_seen")})
            label = days[-1] if days else dt.date.today().isoformat()
        rows = [j for j in active if (j.get("first_seen") or "")[:10] == label]

    if not rows:
        raise SystemExit(f"没有找到 {label} 的新增数据")
    export(rows, label)


if __name__ == "__main__":
    main()
