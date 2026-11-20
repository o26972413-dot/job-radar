#!/usr/bin/env python3
"""内容选题专用导出器 —— 从 job-radar 的 jobs.json 导出每日新增。

两种口径（都产出，互不覆盖）：
  1. 今日发布（主清单，文件名 YYYY-MM-DD.*）
     按 publish_time（公司实际发布日）归一化后 = 当天。
     这是内容选题真正要的「公司今天新放的岗位」。
  2. 首次发现（补充清单，文件名 YYYY-MM-DD-首次发现.*）
     按 first_seen（系统今天首次抓到）筛选，可能含几天前发布的旧岗。

与官方 notify_preview.py 的区别：
  - 官方：只筛「27届 + 产品/数据方向 + 高分」，是个人求职精准推荐
  - 本脚本：不限届别/方向，面向内容选题「数据尽量全」

输出（data/content_digest/）：
  YYYY-MM-DD.csv / .md / .json          —— 今日发布（主清单）
  YYYY-MM-DD-首次发现.csv/.md/.json     —— 首次发现（补充）
  latest.txt                             —— 主清单文件名，供 Pages 精确定位

用法：
  python scripts/content_export.py            # 用 first_seen 最新日期作为目标日
  python scripts/content_export.py 2026-11-20 # 指定日期
  python scripts/content_export.py --all      # 导出当前全量在架岗位（仅首次发现口径）
"""
from __future__ import annotations

import csv
import datetime as dt
import html
import json
import os
import re
import sys
from collections import Counter

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JOBS = os.path.join(BASE, "data", "jobs.json")
OUT_DIR = os.path.join(BASE, "data", "content_digest")

# 北京时间（与 workflow 的 Asia/Shanghai 一致）
BJ_TZ = dt.timezone(dt.timedelta(hours=8))

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


def normalize_publish_date(v):
    """把 publish_time 归一化为 YYYY-MM-DD；无法识别或为空返回 None。

    已实测的三种格式（来自 2026-11-20 云端 jobs.json）：
      ISO        '2026-11-20' / '2026-11-20 10:15:00'
      中文        '2026年11月20日'
      Unix 时间戳 '1795140905'(10位秒) / '1795140905000'(13位毫秒)
    时间戳按北京时间换算（已验证 1795140905 = 北京 2026-11-20 10:15）。
    """
    s = norm(v).strip()
    if not s:
        return None

    # Unix 时间戳：10 位秒 / 13 位毫秒
    if re.fullmatch(r"\d{10,13}", s):
        try:
            ts = int(s)
            if len(s) == 13:
                ts /= 1000
            return dt.datetime.fromtimestamp(ts, BJ_TZ).strftime("%Y-%m-%d")
        except (ValueError, OSError, OverflowError):
            return None

    # ISO：2026-11-20 或 2026-11-20T10:15:00+08:00
    m = re.match(r"(\d{4})-(\d{1,2})-(\d{1,2})", s)
    if m:
        y, mo, d = (int(x) for x in m.groups())
        try:
            return dt.date(y, mo, d).isoformat()
        except ValueError:
            return None

    # 中文：2026年11月20日
    m = re.match(r"(\d{4})年(\d{1,2})月(\d{1,2})", s)
    if m:
        y, mo, d = (int(x) for x in m.groups())
        try:
            return dt.date(y, mo, d).isoformat()
        except ValueError:
            return None

    return None


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


def render_html(rows: list[dict], label: str, kind: str) -> str:
    """把清单渲染成一个可直接看的 HTML 页（不依赖任何 CDN / JS）。"""
    e = html.escape
    by_company = Counter(j.get("company_name", "未知") for j in rows)
    parts = [
        "<!doctype html><html lang='zh-CN'><head><meta charset='utf-8'>",
        "<meta name='viewport' content='width=device-width,initial-scale=1'>",
        f"<title>校招选题清单 {label} · {kind}</title>",
        "<style>",
        "body{font-family:-apple-system,'PingFang SC',sans-serif;max-width:900px;margin:0 auto;padding:20px;color:#1a1a1a;line-height:1.6}",
        "h1{font-size:22px}h2{font-size:18px;margin-top:28px;border-bottom:2px solid #eee;padding-bottom:6px}",
        "h3{font-size:15px;margin:22px 0 8px;color:#0b62d0}",
        "table{border-collapse:collapse;width:100%;max-width:420px}td,th{border:1px solid #ddd;padding:5px 10px;text-align:left}",
        "th{background:#f5f7fa}td:last-child,th:last-child{text-align:right}",
        "ul{padding-left:20px}li{margin:4px 0}a{color:#0b62d0;text-decoration:none}",
        ".meta{color:#666;font-size:13px}.empty{color:#999}",
        "</style></head><body>",
        f"<h1>校招选题清单 · {label} · {kind}</h1>",
        f"<p class='meta'>共 <b>{len(rows)}</b> 条岗位，来自 <b>{len(by_company)}</b> 家公司 · 数据来自公开校招信息 · 投递请用官网链接</p>",
    ]
    if not rows:
        parts.append("<p class='empty'>当日暂无可确认的该类岗位。</p>")
    parts += ["<h2>公司分布</h2>", "<table><tr><th>公司</th><th>岗位数</th></tr>"]
    for comp, c in by_company.most_common():
        parts.append(f"<tr><td>{e(comp)}</td><td>{c}</td></tr>")
    parts.append("</table><h2>全部岗位</h2>")
    last_company = None
    for j in sorted(rows, key=lambda x: (x.get("company_name", ""), x.get("title", ""))):
        comp = j.get("company_name", "未知")
        if comp != last_company:
            parts.append(f"<h3>{e(comp)}</h3><ul>")
            last_company = comp
        title = norm(j.get("title"))
        loc = norm(j.get("location"))
        pub = norm(j.get("publish_time"))
        url = norm(j.get("official_url"))
        meta = " · ".join(x for x in [loc, pub] if x)
        item = f"<b>{e(title)}</b>" + (f" <span class='meta'>({e(meta)})</span>" if meta else "")
        if url:
            item += f" <a href='{e(url, quote=True)}' target='_blank' rel='noopener'>投递→</a>"
        parts.append(f"<li>{item}</li>")
    if rows:
        parts.append("</ul>")
    parts.append("</body></html>")
    return "\n".join(parts)


def export(rows: list[dict], label: str, kind: str) -> None:
    """导出一份清单。kind 写入标题，用于区分「今日发布」与「首次发现」。"""
    os.makedirs(OUT_DIR, exist_ok=True)
    csv_path = os.path.join(OUT_DIR, f"{label}.csv")
    md_path = os.path.join(OUT_DIR, f"{label}.md")
    json_path = os.path.join(OUT_DIR, f"{label}.json")
    html_path = os.path.join(OUT_DIR, f"{label}.html")

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
        f"# 校招选题清单 · {label} · {kind}",
        "",
        f"共 **{len(rows)}** 条岗位，来自 **{len(by_company)}** 家公司。",
        "",
    ]
    if not rows:
        lines += ["> 当日暂无可确认的该类岗位。", ""]

    lines += ["## 公司分布", "", "| 公司 | 岗位数 |", "|---|---:|"]
    for comp, c in by_company.most_common():
        lines.append(f"| {comp} | {c} |")
    lines += ["", "## 全部岗位", ""]
    last_company = None
    for j in sorted(rows, key=lambda x: (x.get("company_name", ""), x.get("title", ""))):
        comp = j.get("company_name", "未知")
        if comp != last_company:
            lines += [f"### {comp}", ""]
            last_company = comp
        title = norm(j.get("title"))
        loc = norm(j.get("location"))
        pub = norm(j.get("publish_time"))
        url = norm(j.get("official_url"))
        tags = "/".join(j.get("tags", [])[:5]) if isinstance(j.get("tags"), list) else norm(j.get("tags"))
        meta = "｜".join(x for x in [loc, f"发布:{pub}" if pub else "", tags] if x)
        lines.append(f"- **{title}**" + (f"｜{meta}" if meta else "") + (f"｜[投递]({url})" if url else ""))
    lines.append("")

    with open(md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    with open(html_path, "w", encoding="utf-8") as f:
        f.write(render_html(rows, label, kind))

    print(f"✅ [{kind}] 导出 {len(rows)} 条 → {OUT_DIR}/{label}.*")


def main():
    args = sys.argv[1:]
    all_mode = "--all" in args
    args = [a for a in args if a != "--all"]

    jobs = json.load(open(JOBS, encoding="utf-8"))
    active = [j for j in jobs if not j.get("gone")]

    if all_mode:
        label = dt.datetime.now(BJ_TZ).date().isoformat() + "-全量"
        export(active, label, "全量在架")
        return

    if args:
        label = args[0]
    else:
        days = sorted({(j.get("first_seen") or "")[:10] for j in active if j.get("first_seen")})
        label = days[-1] if days else dt.datetime.now(BJ_TZ).date().isoformat()

    # 口径1：今日发布（主清单）—— 公司实际发布日 = 目标日
    just_published = [j for j in active if normalize_publish_date(j.get("publish_time")) == label]

    # 口径2：首次发现（补充）—— 系统首次抓到 = 目标日
    first_found = [j for j in active if (j.get("first_seen") or "")[:10] == label]

    if not just_published and not first_found:
        raise SystemExit(f"没有找到 {label} 的新增数据")

    # 主清单：文件名不带后缀（保持既有直链 digest.html / YYYY-MM-DD.md 不变）
    export(just_published, label, "今日发布")
    # 补充清单
    export(first_found, label + "-首次发现", "首次发现")

    # 供 Pages 精确定位主清单，避免按修改时间猜文件
    with open(os.path.join(OUT_DIR, "latest.txt"), "w", encoding="utf-8") as f:
        f.write(f"{label}.md\n")

    # 控制台汇总（便于人工核对）
    pub_companies = Counter(j.get("company_name", "未知") for j in just_published)
    print(f"\n📊 {label} 今日发布 {len(just_published)} 条 / {len(pub_companies)} 家；"
          f"首次发现 {len(first_found)} 条")
    for comp, c in pub_companies.most_common(8):
        print(f"   {comp}: {c}")


if __name__ == "__main__":
    main()
