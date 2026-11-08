"""엑셀(.xlsx)·파워포인트(.pptx) 내보내기."""
from __future__ import annotations

import io
from datetime import date, timedelta

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.util import Emu, Inches, Pt

# 클로드 CI 계열 색
CREAM, PAPER, INK, MUTED, LINE = "F5F0E8", "FAF9F5", "1F1E1D", "73726C", "E3DACC"
CLAY, CLAY_SOFT, SLATE, OLIVE, SKY = "C96442", "F0D9CC", "5E5D59", "788C5D", "6A9BCC"
KFONT = "맑은 고딕"


def _date(s):
    return date.fromisoformat(s) if s else None


# ================================================================== Excel

def build_xlsx(b: dict, usage: dict) -> bytes:
    wb = Workbook()
    thin = Side(style="thin", color=LINE)
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    head_fill = PatternFill("solid", fgColor=CLAY)
    head_font = Font(name=KFONT, bold=True, color="FFFFFF", size=10)
    base = Font(name=KFONT, size=10, color=INK)
    bold = Font(name=KFONT, size=10, bold=True, color=INK)
    crit_font = Font(name=KFONT, size=10, color=CLAY)
    sum_fill = PatternFill("solid", fgColor="EFE9DE")
    p = b["project"]

    def header(ws, row, cols, widths=None):
        for i, h in enumerate(cols, start=1):
            c = ws.cell(row=row, column=i, value=h)
            c.fill, c.font, c.border = head_fill, head_font, border
            c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        if widths:
            for i, w in enumerate(widths, start=1):
                ws.column_dimensions[get_column_letter(i)].width = w
        ws.row_dimensions[row].height = 22

    def title(ws, text, sub):
        ws["A1"] = text
        ws["A1"].font = Font(name=KFONT, size=15, bold=True, color=INK)
        ws["A2"] = sub
        ws["A2"].font = Font(name=KFONT, size=9, color=MUTED)

    sub = (f"시작 {b['project_start']} · 예측 완료 {b['project_finish']} · 진척 기준일 {b['status_date'] or '-'}"
           f" · 기준선 완료 {b['baseline_finish'] or '-'}")

    # ---- 1. 작업 목록
    ws = wb.active
    ws.title = "작업목록"
    title(ws, f"{p['name']} — 작업 목록", sub)
    cols = ["ID", "WBS", "작업명", "기간(일)", "시작", "완료", "선행작업", "자원", "진척률",
            "총여유(일)", "주공정", "기준선 시작", "기준선 완료", "완료 차이(일)", "상태", "비용(원)"]
    header(ws, 4, cols, [5, 7, 36, 8, 11, 11, 12, 26, 8, 9, 7, 11, 11, 10, 7, 13])
    r = 5
    for t in b["tasks"]:
        vals = [t["row"], t["wbs"], t["name"], t["forecast_duration"] if t["summary"] else t["duration"],
                _date(t["start"]), _date(t["finish"]), t["predecessors"], t["resources"], t["pct"] / 100,
                t["total_float"], "●" if t["critical"] else "", _date(t["baseline_start"]),
                _date(t["baseline_finish"]), t["finish_var"], t["status"], t["cost"]]
        for ci, v in enumerate(vals, start=1):
            c = ws.cell(row=r, column=ci, value=v)
            c.border = border
            c.font = bold if t["summary"] else (crit_font if t["critical"] and ci in (3, 11) else base)
            if isinstance(v, date):
                c.number_format = "yyyy-mm-dd"
                c.alignment = Alignment(horizontal="center")
            if ci == 9:
                c.number_format = "0%"
            if ci == 16:
                c.number_format = "#,##0"
            if t["summary"]:
                c.fill = sum_fill
        ws.cell(row=r, column=3).alignment = Alignment(indent=(t["level"] - 1) * 2)
        if (t["finish_var"] or 0) > 0:
            ws.cell(row=r, column=14).font = Font(name=KFONT, size=10, bold=True, color="B3261E")
        r += 1
    ws.freeze_panes = "D5"
    ws.auto_filter.ref = f"A4:{get_column_letter(len(cols))}{r - 1}"

    # ---- 2. 간트
    wg = wb.create_sheet("간트차트")
    title(wg, f"{p['name']} — 간트 차트", sub + " · ■주공정 ■일반 ◆마일스톤 ▒기준선")
    start = _date(b["project_start"])
    finish = max([_date(b["project_finish"])] + [_date(t["baseline_finish"]) for t in b["tasks"] if t["baseline_finish"]])
    span = (finish - start).days + 1
    daily = span <= 130
    step = 1 if daily else 7
    if not daily:
        start = start - timedelta(days=start.weekday())
    slots = []
    d = start
    while d <= finish:
        slots.append(d)
        d += timedelta(days=step)
    header(wg, 4, ["ID", "작업명", "기간", "진척률"] + [s.strftime("%m/%d") if not daily else s.strftime("%d")
                                                for s in slots], [5, 34, 6, 7])
    # 월 표시 행
    for i, s in enumerate(slots):
        if i == 0 or s.month != slots[i - 1].month:
            c = wg.cell(row=3, column=5 + i, value=s.strftime("%Y-%m"))
            c.font = Font(name=KFONT, size=9, bold=True, color=CLAY)
    for i in range(len(slots)):
        wg.column_dimensions[get_column_letter(5 + i)].width = 3.2 if daily else 5
        wg.cell(row=4, column=5 + i).font = Font(name=KFONT, size=8, bold=True, color="FFFFFF")
    holidays = set(b["holidays"])
    fills = {"crit": PatternFill("solid", fgColor=CLAY), "norm": PatternFill("solid", fgColor=SKY),
             "sum": PatternFill("solid", fgColor=INK), "done": PatternFill("solid", fgColor=OLIVE),
             "base": PatternFill("solid", fgColor="D8D2C6"), "off": PatternFill("solid", fgColor="F2EEE6")}
    r = 5
    for t in b["tasks"]:
        wg.cell(row=r, column=1, value=t["row"]).font = base
        c = wg.cell(row=r, column=2, value=("  " * (t["level"] - 1)) + t["name"])
        c.font = bold if t["summary"] else base
        wg.cell(row=r, column=3, value=t["forecast_duration"]).font = base
        pc = wg.cell(row=r, column=4, value=t["pct"] / 100)
        pc.number_format, pc.font = "0%", base
        ts, tf = _date(t["start"]), _date(t["finish"])
        bs, bf = _date(t["baseline_start"]), _date(t["baseline_finish"])
        for i, s in enumerate(slots):
            e = s + timedelta(days=step - 1)
            cell = wg.cell(row=r, column=5 + i)
            cell.border = Border(left=Side(style="hair", color=LINE))
            if daily and (s.weekday() >= 5 and b["skip_weekends"] or s.isoformat() in holidays):
                cell.fill = fills["off"]
            if bs and bf and s <= bf and e >= bs and not (ts <= e and tf >= s):
                cell.fill = fills["base"]
            if ts <= e and tf >= s:
                if t["milestone"]:
                    cell.value, cell.font = "◆", Font(name=KFONT, size=9, color=INK, bold=True)
                    cell.alignment = Alignment(horizontal="center")
                else:
                    key = "sum" if t["summary"] else ("done" if t["pct"] >= 100 else ("crit" if t["critical"] else "norm"))
                    cell.fill = fills[key]
        r += 1
    if b["status_date"]:
        sd = _date(b["status_date"])
        for i, s in enumerate(slots):
            if s <= sd <= s + timedelta(days=step - 1):
                wg.cell(row=4, column=5 + i).fill = PatternFill("solid", fgColor=INK)
    wg.freeze_panes = "E5"

    # ---- 3. 자원
    wr = wb.create_sheet("자원")
    title(wr, f"{p['name']} — 자원 시트 및 부하", "최대 단위를 넘는 기간은 붉게 표시")
    header(wr, 4, ["자원명", "유형", "그룹", "최대(%)", "단가(원/일)", "투입(인·일)", "비용(원)", "과부하 일수"]
           + usage["labels"], [16, 10, 10, 8, 12, 11, 13, 10])
    for i in range(len(usage["labels"])):
        wr.column_dimensions[get_column_letter(9 + i)].width = 8
    r = 5
    for u in usage["rows"]:
        res = u["resource"]
        vals = [res["name"], res["type"], res["grp"], res["max_units"], res["rate"], u["work_days"], u["cost"],
                len(u["over_days"])] + [round(v) if v else None for v in u["peaks"]]
        for ci, v in enumerate(vals, start=1):
            c = wr.cell(row=r, column=ci, value=v)
            c.font, c.border = base, border
            if ci in (5, 7):
                c.number_format = "#,##0"
            if ci > 8 and v:
                over = v > (res["max_units"] or 100)
                c.fill = PatternFill("solid", fgColor="F4C7BB" if over else "E8EEF5")
                if over:
                    c.font = Font(name=KFONT, size=10, bold=True, color="B3261E")
        r += 1

    # ---- 4. 지연 분석
    wd = wb.create_sheet("지연분석")
    title(wd, f"{p['name']} — 기준선 대비 지연 분석", sub)
    k = b["kpi"]
    kp = [("기준선 완료일", b["baseline_finish"] or "-"), ("예측 완료일", b["project_finish"]),
          ("완료일 차이(작업일)", k.get("finish_var") if k.get("finish_var") is not None else "-"),
          ("계획 공정률(%)", k.get("planned_pct") if k.get("planned_pct") is not None else "-"),
          ("실적 공정률(%)", k.get("actual_pct")), ("SPI", k.get("spi") if k.get("spi") is not None else "-"),
          ("지연 / 주의 작업", f"{k.get('delayed')} / {k.get('warning')}"), ("총 비용(원)", k.get("total_cost"))]
    for i, (a, v) in enumerate(kp):
        wd.cell(row=4 + i, column=1, value=a).font = bold
        c = wd.cell(row=4 + i, column=2, value=v)
        c.font = base
        if isinstance(v, (int, float)) and i == 7:
            c.number_format = "#,##0"
    wd.column_dimensions["A"].width = 20
    wd.column_dimensions["B"].width = 34
    hr = 4 + len(kp) + 2
    header(wd, hr, ["ID", "작업명", "상태", "주공정", "기준선 완료", "예측 완료", "완료 차이(일)", "계획 진척", "실적 진척", "총여유"])
    for col, w in zip("CDEFGHIJ", [8, 8, 12, 12, 12, 10, 10, 8]):
        wd.column_dimensions[col].width = w
    r = hr + 1
    for t in b["tasks"]:
        if t["summary"] or t["status"] not in ("지연", "주의"):
            continue
        vals = [t["row"], t["name"], t["status"], "●" if t["critical"] else "", _date(t["baseline_finish"]),
                _date(t["finish"]), t["finish_var"],
                None if t["planned_pct"] is None else t["planned_pct"] / 100, t["pct"] / 100, t["total_float"]]
        for ci, v in enumerate(vals, start=1):
            c = wd.cell(row=r, column=ci, value=v)
            c.font, c.border = base, border
            if isinstance(v, date):
                c.number_format = "yyyy-mm-dd"
            if ci in (8, 9):
                c.number_format = "0%"
        if t["status"] == "지연":
            wd.cell(row=r, column=3).font = Font(name=KFONT, size=10, bold=True, color="B3261E")
        r += 1

    for sheet in wb.worksheets:
        sheet.sheet_view.showGridLines = sheet.title != "간트차트"
        sheet.page_setup.orientation = "landscape"
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ================================================================== PowerPoint

def _rgb(h):
    return RGBColor.from_string(h)


def _box(slide, x, y, w, h, fill=None, line=None, shape=MSO_SHAPE.RECTANGLE):
    s = slide.shapes.add_shape(shape, x, y, w, h)
    if fill:
        s.fill.solid()
        s.fill.fore_color.rgb = _rgb(fill)
    else:
        s.fill.background()
    if line:
        s.line.color.rgb = _rgb(line)
        s.line.width = Pt(0.75)
    else:
        s.line.fill.background()
    s.shadow.inherit = False
    return s


def _text(slide, x, y, w, h, text, size=12, bold=False, color=INK, align=PP_ALIGN.LEFT, font=KFONT,
          anchor=MSO_ANCHOR.TOP):
    tb = slide.shapes.add_textbox(x, y, w, h)
    tf = tb.text_frame
    tf.word_wrap = True
    tf.margin_left = tf.margin_right = Emu(0)
    tf.margin_top = tf.margin_bottom = Emu(0)
    tf.vertical_anchor = anchor
    lines = text if isinstance(text, list) else [text]
    for i, ln in enumerate(lines):
        para = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        para.alignment = align
        run = para.add_run()
        run.text = str(ln)
        run.font.size, run.font.bold, run.font.name = Pt(size), bold, font
        run.font.color.rgb = _rgb(color)
    return tb


def _slide(prs, title, kicker=""):
    s = prs.slides.add_slide(prs.slide_layouts[6])
    bg = s.background.fill
    bg.solid()
    bg.fore_color.rgb = _rgb(PAPER)
    _box(s, Inches(0.5), Inches(0.42), Inches(0.08), Inches(0.5), CLAY)
    if kicker:
        _text(s, Inches(0.72), Inches(0.36), Inches(9), Inches(0.25), kicker, 10, True, CLAY)
    _text(s, Inches(0.72), Inches(0.58), Inches(11.5), Inches(0.5), title, 22, True, INK)
    _box(s, Inches(0.5), Inches(7.05), Inches(12.33), Emu(9525), LINE)
    return s


def _table(slide, x, y, w, rows, widths, font=10, row_h=0.3):
    shape = slide.shapes.add_table(len(rows), len(rows[0]), x, y, w, Inches(row_h * len(rows)))
    tbl = shape.table
    for i, wv in enumerate(widths):
        tbl.columns[i].width = Inches(wv)
    for ri, row in enumerate(rows):
        tbl.rows[ri].height = Inches(row_h)
        for ci, v in enumerate(row):
            cell = tbl.cell(ri, ci)
            cell.fill.solid()
            cell.fill.fore_color.rgb = _rgb(CLAY if ri == 0 else ("FFFFFF" if ri % 2 else CREAM))
            cell.margin_left = cell.margin_right = Inches(0.06)
            cell.margin_top = cell.margin_bottom = Inches(0.02)
            cell.vertical_anchor = MSO_ANCHOR.MIDDLE
            tf = cell.text_frame
            tf.paragraphs[0].text = ""
            run = tf.paragraphs[0].add_run()
            run.text = "" if v is None else str(v)
            run.font.size, run.font.name = Pt(font), KFONT
            run.font.bold = ri == 0
            run.font.color.rgb = _rgb("FFFFFF" if ri == 0 else INK)
    return tbl


def build_pptx(b: dict, usage: dict) -> bytes:
    prs = Presentation()
    prs.slide_width, prs.slide_height = Inches(13.333), Inches(7.5)
    p, k = b["project"], b["kpi"]

    # ---- 1. 표지
    s = prs.slides.add_slide(prs.slide_layouts[6])
    s.background.fill.solid()
    s.background.fill.fore_color.rgb = _rgb(CREAM)
    _box(s, Inches(0), Inches(0), Inches(0.35), Inches(7.5), CLAY)
    _text(s, Inches(1.0), Inches(2.0), Inches(10), Inches(0.4), "PROJECT SCHEDULE REPORT", 13, True, CLAY)
    _text(s, Inches(1.0), Inches(2.5), Inches(11), Inches(1.4), p["name"], 40, True, INK)
    _text(s, Inches(1.0), Inches(3.9), Inches(11), Inches(0.8), p.get("description") or "", 14, False, SLATE)
    _text(s, Inches(1.0), Inches(5.6), Inches(11), Inches(0.4),
          f"진척 기준일 {b['status_date'] or '-'}   ·   작성일 {date.today().isoformat()}   ·   PM {p.get('manager') or '-'}",
          12, False, MUTED)

    # ---- 2. 요약 KPI
    s = _slide(prs, "프로젝트 일정 요약", "SUMMARY")
    fv = k.get("finish_var")
    cards = [
        ("예측 완료일", b["project_finish"], f"기준선 {b['baseline_finish'] or '미설정'}"),
        ("완료일 차이", "-" if fv is None else (f"+{fv}일" if fv > 0 else f"{fv}일"), "작업일 기준 (+ 지연)"),
        ("실적 / 계획 공정률", f"{k.get('actual_pct')}%",
         f"계획 {k.get('planned_pct') if k.get('planned_pct') is not None else '-'}% · SPI {k.get('spi') if k.get('spi') is not None else '-'}"),
        ("지연 · 주의 작업", f"{k.get('delayed')} · {k.get('warning')}건", f"주공정 작업 {k.get('critical_count')}건"),
    ]
    cw = 2.88
    for i, (lab, val, note) in enumerate(cards):
        x = Inches(0.5 + i * (cw + 0.27))
        hot = i == 1 and fv and fv > 0
        _box(s, x, Inches(1.45), Inches(cw), Inches(1.75), "FFFFFF", LINE, MSO_SHAPE.ROUNDED_RECTANGLE).adjustments[0] = 0.06
        _text(s, x + Inches(0.25), Inches(1.65), Inches(cw - 0.5), Inches(0.3), lab, 11, True, MUTED)
        _text(s, x + Inches(0.25), Inches(2.0), Inches(cw - 0.5), Inches(0.6), val, 26, True, CLAY if hot else INK)
        _text(s, x + Inches(0.25), Inches(2.72), Inches(cw - 0.5), Inches(0.3), note, 10, False, MUTED)
    # 요약 단계별 표
    rows = [["WBS", "단계", "시작", "완료", "기간", "진척률", "상태"]]
    for t in b["tasks"]:
        if t["level"] == 1:
            rows.append([t["wbs"], t["name"], t["start"], t["finish"], f"{t['forecast_duration']}일", f"{t['pct']:g}%",
                         t["status"]])
    _table(s, Inches(0.5), Inches(3.5), Inches(12.33), rows[:11], [0.8, 5.2, 1.5, 1.5, 1.1, 1.1, 1.13], 11, 0.34)

    # ---- 3. 간트 (페이지 분할)
    tasks = b["tasks"]
    pstart = _date(b["project_start"])
    pend = max([_date(b["project_finish"])] + [_date(t["baseline_finish"]) for t in tasks if t["baseline_finish"]])
    total = max((pend - pstart).days + 1, 1)
    per = 18
    for pg in range(0, len(tasks), per):
        chunk = tasks[pg:pg + per]
        s = _slide(prs, "간트 차트" + (f" ({pg // per + 1})" if len(tasks) > per else ""), "GANTT")
        lx, gx, gw = Inches(0.5), Inches(4.4), Inches(8.43)
        top, rh = Inches(1.65), Inches(0.28)
        # 월·주 눈금
        d = pstart
        while d <= pend:
            if d.day == 1 or d == pstart:
                x = gx + int(gw * (d - pstart).days / total)
                _text(s, x + Inches(0.03), Inches(1.28), Inches(1.2), Inches(0.25), d.strftime("%Y.%m"), 9, True, SLATE)
                _box(s, x, Inches(1.28), Emu(9525), rh * len(chunk) + Inches(0.4), LINE)
            d += timedelta(days=1)
        for i, t in enumerate(chunk):
            y = top + rh * i
            if i % 2 == 0:
                _box(s, lx, y, Inches(12.33), rh, "F3EEE5")
            _text(s, lx + Inches(0.05 + 0.18 * (t["level"] - 1)), y + Inches(0.05), Inches(3.8), rh,
                  f"{t['row']}  {t['name']}", 9, t["summary"], CLAY if t["critical"] and not t["summary"] else INK)
            ts, tf = _date(t["start"]), _date(t["finish"])
            x1 = gx + int(gw * (ts - pstart).days / total)
            x2 = gx + int(gw * ((tf - pstart).days + 1) / total)
            if t["baseline_start"] and not t["summary"]:
                bs, bf = _date(t["baseline_start"]), _date(t["baseline_finish"])
                bx1 = gx + int(gw * (bs - pstart).days / total)
                bx2 = gx + int(gw * ((bf - pstart).days + 1) / total)
                _box(s, bx1, y + Inches(0.19), max(bx2 - bx1, Inches(0.04)), Inches(0.06), "BDB5A8")
            if t["milestone"]:
                _box(s, x1 - Inches(0.08), y + Inches(0.05), Inches(0.16), Inches(0.16), INK, None, MSO_SHAPE.DIAMOND)
                _text(s, x1 + Inches(0.12), y + Inches(0.04), Inches(1.2), rh, ts.strftime("%m/%d"), 8, False, MUTED)
            elif t["summary"]:
                _box(s, x1, y + Inches(0.08), max(x2 - x1, Inches(0.05)), Inches(0.08), INK)
            else:
                col = OLIVE if t["pct"] >= 100 else (CLAY if t["critical"] else SKY)
                w = max(x2 - x1, Inches(0.05))
                _box(s, x1, y + Inches(0.05), w, Inches(0.14), col)
                if 0 < t["pct"] < 100:
                    _box(s, x1, y + Inches(0.1), int(w * t["pct"] / 100), Inches(0.04), INK)
        if b["status_date"]:
            sd = _date(b["status_date"])
            if pstart <= sd <= pend:
                x = gx + int(gw * ((sd - pstart).days + 1) / total)
                _box(s, x, Inches(1.5), Emu(19050), rh * len(chunk) + Inches(0.2), "B3261E")
                _text(s, x + Inches(0.04), Inches(1.5), Inches(1.5), Inches(0.2), "진척 기준일", 8, True, "B3261E")
        _text(s, Inches(0.5), Inches(6.75), Inches(12), Inches(0.25),
              "■ 주공정   ■ 일반   ■ 완료   ▬ 요약   ◆ 마일스톤   ─ 기준선(회색)   │ 진척 기준일", 9, False, MUTED)

    # ---- 4. 지연 작업
    s = _slide(prs, "기준선 대비 지연 작업", "DELAY")
    rows = [["ID", "작업명", "상태", "주공정", "기준선 완료", "예측 완료", "차이(일)", "계획/실적"]]
    for t in tasks:
        if not t["summary"] and t["status"] in ("지연", "주의"):
            rows.append([t["row"], t["name"], t["status"], "●" if t["critical"] else "", t["baseline_finish"] or "-",
                         t["finish"], t["finish_var"] if t["finish_var"] is not None else "-",
                         f"{t['planned_pct'] if t['planned_pct'] is not None else '-'}% / {t['pct']:g}%"])
    if len(rows) == 1:
        _text(s, Inches(0.72), Inches(1.6), Inches(11), Inches(0.5),
              "기준선 대비 지연된 작업이 없습니다." if b["baseline_finish"] else "기준선이 없어 지연을 판정할 수 없습니다. 기준선을 먼저 저장하세요.",
              14, False, SLATE)
    else:
        _table(s, Inches(0.5), Inches(1.45), Inches(12.33), rows[:16], [0.6, 4.6, 0.9, 0.9, 1.5, 1.5, 1.0, 1.33], 10, 0.32)

    # ---- 5. 주공정
    s = _slide(prs, "주공정(Critical Path)", "CRITICAL PATH")
    crit = sorted([t for t in tasks if t["critical"] and not t["summary"]], key=lambda t: (t["es"], t["row"]))
    # 흐름 칩
    x, y = Inches(0.5), Inches(1.45)
    for t in crit[:14]:
        w = Inches(1.65)
        if x + w > Inches(12.9):
            x, y = Inches(0.5), y + Inches(0.85)
        bx = _box(s, x, y, w, Inches(0.62), "FFFFFF", CLAY, MSO_SHAPE.ROUNDED_RECTANGLE)
        bx.adjustments[0] = 0.15
        _text(s, x + Inches(0.08), y + Inches(0.06), w - Inches(0.16), Inches(0.5),
              [f"{t['row']}. {t['name'][:14]}", f"{t['start'][5:]}~{t['finish'][5:]}"], 9, False, INK)
        x += w + Inches(0.12)
    rows = [["ID", "작업명", "시작", "완료", "기간", "총여유", "자원"]]
    for t in crit[:12]:
        rows.append([t["row"], t["name"], t["start"], t["finish"], f"{t['forecast_duration']}일", t["total_float"],
                     t["resources"]])
    _table(s, Inches(0.5), y + Inches(0.95), Inches(12.33), rows, [0.6, 4.0, 1.4, 1.4, 0.9, 0.9, 3.13], 10, 0.3)

    # ---- 6. 자원
    s = _slide(prs, "자원 투입 및 부하", "RESOURCES")
    rows = [["자원명", "유형", "최대", "투입(인·일)", "비용(원)", "최대 부하", "과부하 일수"]]
    for u in usage["rows"]:
        r = u["resource"]
        rows.append([r["name"], r["type"], f"{r['max_units']:g}%", u["work_days"], f"{u['cost']:,}",
                     f"{u['max_peak']:g}%", len(u["over_days"]) or "-"])
    _table(s, Inches(0.5), Inches(1.45), Inches(12.33), rows[:15], [2.6, 1.6, 1.2, 1.7, 2.2, 1.5, 1.53], 11, 0.33)

    buf = io.BytesIO()
    prs.save(buf)
    return buf.getvalue()
