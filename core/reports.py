"""보고서 생성: 표 데이터 + 인쇄용 HTML + 엑셀."""
from __future__ import annotations

import html
import io
from datetime import date

import pandas as pd


def _fmt(v) -> str:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return ""
    if isinstance(v, (date, pd.Timestamp)):
        return v.strftime("%Y-%m-%d")
    if isinstance(v, bool):
        return "●" if v else ""
    if isinstance(v, float):
        return f"{v:,.1f}" if v % 1 else f"{v:,.0f}"
    return html.escape(str(v))


def df_to_html(df: pd.DataFrame, highlight_col: str | None = None) -> str:
    head = "".join(f"<th>{html.escape(str(c))}</th>" for c in df.columns)
    rows = []
    for _, r in df.iterrows():
        cls = ' class="hl"' if highlight_col and bool(r.get(highlight_col)) else ""
        rows.append(f"<tr{cls}>" + "".join(f"<td>{_fmt(v)}</td>" for v in r.values) + "</tr>")
    return f"<table><thead><tr>{head}</tr></thead><tbody>{''.join(rows)}</tbody></table>"


def html_report(title: str, meta: dict[str, str], sections: list[tuple[str, str]]) -> str:
    meta_html = "".join(f"<div><b>{html.escape(k)}</b> {html.escape(str(v))}</div>" for k, v in meta.items())
    body = "".join(f"<h2>{html.escape(h)}</h2>{content}" for h, content in sections)
    return f"""<!doctype html><html lang="ko"><head><meta charset="utf-8"><title>{html.escape(title)}</title>
<style>
body{{font-family:'Malgun Gothic','Apple SD Gothic Neo','Noto Sans KR',sans-serif;margin:28px;color:#0f172a;font-size:12px}}
h1{{font-size:20px;border-bottom:3px solid #1e3a8a;padding-bottom:6px}}
h2{{font-size:15px;margin-top:26px;color:#1e3a8a}}
.meta{{display:grid;grid-template-columns:repeat(3,1fr);gap:4px 16px;background:#f1f5f9;padding:10px;border-radius:6px}}
table{{border-collapse:collapse;width:100%;margin-top:6px}}
th,td{{border:1px solid #cbd5e1;padding:4px 6px;text-align:left}}
th{{background:#e2e8f0}} tr.hl td{{color:#b91c1c;font-weight:600}}
.kpi{{display:flex;gap:10px;flex-wrap:wrap}} .kpi div{{border:1px solid #cbd5e1;border-radius:6px;padding:8px 12px}}
.foot{{margin-top:30px;color:#64748b;font-size:11px}}
@media print{{body{{margin:10mm}} h2{{page-break-after:avoid}}}}
</style></head><body>
<h1>{html.escape(title)}</h1><div class="meta">{meta_html}</div>{body}
<div class="foot">작성일 {date.today():%Y-%m-%d} · 설비정비 일정관리(maint-planner) · 학생 실습용</div>
</body></html>"""


def kpi_html(items: dict[str, str]) -> str:
    return '<div class="kpi">' + "".join(
        f"<div><small>{html.escape(k)}</small><br><b>{html.escape(v)}</b></div>" for k, v in items.items()) + "</div>"


def to_excel(sheets: dict[str, pd.DataFrame]) -> bytes:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        for name, df in sheets.items():
            df.to_excel(xw, sheet_name=name[:31], index=False)
            ws = xw.sheets[name[:31]]
            for i, col in enumerate(df.columns, 1):
                width = max([len(str(col))] + [len(str(v)) for v in df[col].head(200)]) * 1.6
                ws.column_dimensions[ws.cell(1, i).column_letter].width = min(50, max(8, width))
    return buf.getvalue()
