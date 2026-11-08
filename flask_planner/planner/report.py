"""일정 지연 대책 보고서 — OpenAI gpt-4o-mini 로 작성하고 .docx 로 저장.

OPENAI_API_KEY 환경변수가 있으면 gpt-4o-mini(또는 OPENAI_MODEL)를 호출하고,
없거나 호출이 실패하면 일정 데이터만으로 규칙 기반 초안을 만들어 화면이 멈추지 않게 한다.
"""
from __future__ import annotations

import io
import json
import math
import os
from datetime import date, datetime

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

METHODS = ["공정 압축(Crashing)", "공정 중첩(Fast-tracking)", "선후행 관계 재검토", "자원 재배치",
           "범위·사양 조정", "외주·병행 작업", "관리 강화"]


def model_name() -> str:
    return os.environ.get("OPENAI_MODEL", "gpt-4o-mini")


def ai_available() -> bool:
    return bool(os.environ.get("OPENAI_API_KEY"))


# ------------------------------------------------------------------ 입력 데이터 정리

def build_context(b: dict) -> dict:
    s = b["schedule"]
    k = b["kpi"]
    tasks = b["tasks"]
    by_id = {t["id"]: t for t in tasks}
    succ = {}
    for l in b["links"]:
        succ.setdefault(l["pred"], []).append(by_id[l["succ"]]["name"])
    delayed = []
    for t in tasks:
        if t["summary"] or t["status"] not in ("지연", "주의"):
            continue
        delayed.append({
            "id": t["row"], "wbs": t["wbs"], "name": t["name"], "status": t["status"],
            "critical": t["critical"], "baseline_start": t["baseline_start"], "baseline_finish": t["baseline_finish"],
            "forecast_start": t["start"], "forecast_finish": t["finish"], "finish_var_days": t["finish_var"],
            "planned_pct": t["planned_pct"], "actual_pct": t["pct"], "duration": t["duration"],
            "total_float": t["total_float"], "resources": t["resources"], "predecessors": t["predecessors"],
            "successors": succ.get(t["id"], []),
        })
    delayed.sort(key=lambda x: (-(x["finish_var_days"] or 0), x["id"]))
    critical = [{"id": t["row"], "name": t["name"], "start": t["start"], "finish": t["finish"],
                 "duration": t["forecast_duration"], "pct": t["pct"], "resources": t["resources"]}
                for t in tasks if not t["summary"] and t["critical"]]
    return {
        "project": {"name": b["project"]["name"], "manager": b["project"]["manager"],
                    "description": b["project"]["description"], "start": b["project_start"],
                    "status_date": b["status_date"], "baseline_finish": b["baseline_finish"],
                    "forecast_finish": b["project_finish"]},
        "kpi": {"finish_var_days": k.get("finish_var"), "planned_pct": k.get("planned_pct"),
                "actual_pct": k.get("actual_pct"), "spi": k.get("spi"), "tasks": k.get("task_count"),
                "delayed": k.get("delayed"), "warning": k.get("warning"), "critical": k.get("critical_count"),
                "total_cost": k.get("total_cost")},
        "delayed_tasks": delayed[:25],
        "critical_path": critical[:30],
        "resources": [{"name": r["name"], "type": r["type"], "max_units": r["max_units"]} for r in b["resources"]],
    }


SYSTEM_PROMPT = """당신은 제조업 설비투자·생산기술 프로젝트의 일정관리(PMO) 전문 컨설턴트입니다.
주어진 일정 데이터(기준선 대비 예측 일정, 주공정, 지연 작업)를 근거로 경영진에게 올리는 '일정 지연 대책 보고서'를 작성합니다.
작성 원칙:
- 한국어 업무 보고서 문체, 두괄식, 개조식(…함/…임/명사형 종결), 한 항목은 한 문장.
- 모든 판단에는 데이터 근거(작업 ID, 날짜, 지연일, 진척률)를 붙일 것. 데이터에 없는 사실은 '추정'으로 표시.
- 대책은 일정관리 기법(공정 압축 Crashing, 공정 중첩 Fast-tracking, 선후행 관계 재검토, 자원 재배치, 범위·사양 조정, 외주·병행 작업, 관리 강화)으로 분류하고
  담당·완료기한·만회 예상일수·비용/리스크 영향을 구체적으로 제시할 것.
- 주공정(critical) 작업의 만회를 최우선으로 다룰 것. 여유가 있는 작업은 여유 활용을 제안.
반드시 아래 JSON 형식으로만 답하십시오.
{
 "title": "보고서 제목",
 "headline": "경영진이 한 문장으로 알아야 할 핵심 메시지",
 "summary": ["핵심 요약 3~5개"],
 "status": ["지연 현황 분석 3~6개"],
 "causes": [{"area": "구분(설계/조달/시공/자원/관리 등)", "cause": "원인", "evidence": "데이터 근거", "impact": "일정 영향"}],
 "countermeasures": [{"task": "대상 작업(ID 포함)", "method": "기법", "action": "구체적 실행 내용", "owner": "담당", "due": "YYYY-MM-DD", "recovery_days": 0, "cost_impact": "비용·리스크 영향"}],
 "recovery_plan": [{"step": "단계", "period": "기간", "milestone": "확인 지표/마일스톤"}],
 "risks": [{"risk": "리스크", "probability": "상/중/하", "response": "대응"}],
 "requests": ["의사결정·지원 요청 사항"],
 "conclusion": "결론 및 향후 계획 2~3문장"
}"""


def _call_openai(ctx: dict, notes: str) -> dict:
    from openai import OpenAI

    client = OpenAI(timeout=90)
    user = ("다음 프로젝트 일정 데이터를 분석하여 지연 대책 보고서를 작성하십시오.\n\n"
            f"[일정 데이터]\n{json.dumps(ctx, ensure_ascii=False, indent=1)}\n\n"
            f"[현장 메모(지연 원인·제약 조건)]\n{notes or '(없음)'}")
    resp = client.chat.completions.create(
        model=model_name(), temperature=0.4, response_format={"type": "json_object"},
        messages=[{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": user}],
    )
    return json.loads(resp.choices[0].message.content)


def _rule_based(ctx: dict, notes: str) -> dict:
    p, k, delayed = ctx["project"], ctx["kpi"], ctx["delayed_tasks"]
    fv = k.get("finish_var_days") or 0
    crit_delayed = [d for d in delayed if d["critical"]]
    status_date = p.get("status_date") or date.today().isoformat()
    head = (f"진척 기준일({status_date}) 현재 예측 완료일은 {p['forecast_finish']}로 기준선 대비 {fv}작업일 "
            f"{'지연' if fv > 0 else '여유'}이며, 주공정 지연 작업 {len(crit_delayed)}건의 만회가 필요함")
    summary = [
        f"실적 공정률 {k.get('actual_pct')}% / 계획 공정률 {k.get('planned_pct') if k.get('planned_pct') is not None else '-'}%"
        f" (SPI {k.get('spi') if k.get('spi') is not None else '-'})",
        f"지연 작업 {k.get('delayed')}건, 주의 작업 {k.get('warning')}건, 주공정 작업 {k.get('critical')}건",
    ]
    if crit_delayed:
        d = crit_delayed[0]
        summary.append(f"최대 지연 주공정 작업: [{d['id']}] {d['name']} ({d['finish_var_days']}작업일 지연, 진척 {d['actual_pct']}%)")
    summary.append("주공정 작업 공정 압축·중첩으로 기준선 완료일 회복을 목표로 함")
    status = [f"[{d['id']}] {d['name']}: 기준선 완료 {d['baseline_finish']} → 예측 {d['forecast_finish']} "
              f"({d['finish_var_days']}일), 계획 {d['planned_pct']}% 대비 실적 {d['actual_pct']}%"
              for d in delayed[:6]]
    causes, cms = [], []
    for d in delayed[:6]:
        behind = (d["planned_pct"] or 0) - (d["actual_pct"] or 0)
        causes.append({
            "area": "선행 지연 전파" if d["actual_pct"] == 0 else "작업 생산성 저하",
            "cause": ("선행작업 지연으로 착수가 늦어짐" if d["actual_pct"] == 0
                      else "투입 자원 대비 진척 부진"),
            "evidence": f"작업 ID {d['id']}, 계획 대비 진척 차 {behind:.0f}%p, 선행 {d['predecessors'] or '없음'}",
            "impact": f"완료 {d['finish_var_days']}작업일 지연" + (" (주공정 → 프로젝트 완료일 직결)" if d["critical"] else ""),
        })
        rec = max(1, math.ceil((d["duration"] or 1) * 0.2))
        if d["critical"] and d["actual_pct"] > 0:
            method, action = METHODS[0], f"{d['resources'] or '담당 인력'} 외 추가 인력 투입·연장근무로 잔여 기간 단축"
        elif d["critical"]:
            method, action = METHODS[1], "선행 작업 완료 전 부분 착수(SS 관계 + 지연일)로 병행 수행"
        elif (d["total_float"] or 0) > 0:
            method, action, rec = METHODS[6], f"총여유 {d['total_float']}일 범위 내 흡수, 주간 진척 점검", 0
        else:
            method, action = METHODS[3], "비주공정 작업 인력을 해당 작업으로 재배치"
        cms.append({"task": f"[{d['id']}] {d['name']}", "method": method, "action": action,
                    "owner": (d["resources"] or "PM").split(",")[0].split("[")[0].strip(),
                    "due": d["forecast_finish"], "recovery_days": min(rec, max(d["finish_var_days"] or 0, 0)),
                    "cost_impact": "추가 인건비 발생 예상" if method == METHODS[0] else "품질·안전 리스크 관리 필요"})
    if notes:
        causes.append({"area": "현장 의견", "cause": notes[:200], "evidence": "현장 메모", "impact": "검토 필요"})
    return {
        "title": f"{p['name']} 일정 지연 대책 보고",
        "headline": head,
        "summary": summary,
        "status": status or ["기준선 대비 지연 작업이 없음"],
        "causes": causes,
        "countermeasures": cms,
        "recovery_plan": [
            {"step": "1단계 긴급 조치", "period": "1주 이내", "milestone": "주공정 지연 작업 추가 자원 투입 완료"},
            {"step": "2단계 일정 재조정", "period": "2주 이내", "milestone": "공정 중첩 적용 후 일정 재계산·기준선 대비 점검"},
            {"step": "3단계 정상화", "period": "완료 시까지", "milestone": "주간 SPI 0.95 이상 유지"},
        ],
        "risks": [
            {"risk": "추가 인력 투입에 따른 품질·안전 사고", "probability": "중", "response": "작업 전 TBM·작업허가 강화"},
            {"risk": "공정 중첩에 따른 재작업", "probability": "중", "response": "설계 동결 항목 선별 후 부분 착수"},
        ],
        "requests": ["주공정 작업 추가 인력·연장근무 승인", "협력사 일정 단축 협의 지원"],
        "conclusion": "주공정 작업에 대책을 집중하여 기준선 완료일 회복을 추진하고, 주 1회 진척 기준일 갱신으로 효과를 점검하겠음.",
    }


def generate(b: dict, notes: str = "") -> tuple[dict, str]:
    ctx = build_context(b)
    err = None
    if ai_available():
        try:
            content = _call_openai(ctx, notes)
            content["_data"] = ctx
            content["_generated_at"] = datetime.now().isoformat(timespec="seconds")
            return content, model_name()
        except Exception as e:  # noqa: BLE001 — 네트워크·키 오류 시 규칙 기반으로 대체
            err = f"({type(e).__name__}: {str(e)[:160]})"
    content = _rule_based(ctx, notes)
    content["_data"] = ctx
    content["_generated_at"] = datetime.now().isoformat(timespec="seconds")
    if err:
        content["_error"] = err
    return content, "규칙 기반"


# ------------------------------------------------------------------ DOCX

INK = RGBColor(0x1F, 0x1E, 0x1D)
CLAY = RGBColor(0xC9, 0x64, 0x42)
MUTED = RGBColor(0x73, 0x72, 0x6C)
HEAD_FILL = "F0E6DC"
FONT = "맑은 고딕"
SERIF = "바탕"


def _font(run, size=None, bold=None, color=None, name=FONT):
    run.font.name = name
    run._element.get_or_add_rPr().get_or_add_rFonts().set(qn("w:eastAsia"), name)
    if size:
        run.font.size = Pt(size)
    if bold is not None:
        run.bold = bold
    if color is not None:
        run.font.color.rgb = color


def _shade(cell, fill):
    tcPr = cell._element.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), fill)
    tcPr.append(shd)


def _para(doc, text, size=10.5, bold=False, color=INK, align=None, space_after=4, bullet=False):
    p = doc.add_paragraph()
    if bullet:
        r = p.add_run("•  ")
        _font(r, size, False, CLAY)
        p.paragraph_format.left_indent = Cm(0.5)
        p.paragraph_format.first_line_indent = Cm(-0.4)
    r = p.add_run(str(text))
    _font(r, size, bold, color)
    p.paragraph_format.space_after = Pt(space_after)
    if align:
        p.alignment = align
    return p


def _heading(doc, num, text):
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(14)
    p.paragraph_format.space_after = Pt(6)
    r = p.add_run(f"{num}. ")
    _font(r, 13, True, CLAY, SERIF)
    r = p.add_run(text)
    _font(r, 13, True, INK, SERIF)
    # 아래 테두리
    pPr = p._p.get_or_add_pPr()
    bdr = OxmlElement("w:pBdr")
    bottom = OxmlElement("w:bottom")
    for k, v in (("w:val", "single"), ("w:sz", "6"), ("w:space", "2"), ("w:color", "D9CFC2")):
        bottom.set(qn(k), v)
    bdr.append(bottom)
    pPr.append(bdr)


def _table(doc, headers, rows, widths=None):
    t = doc.add_table(rows=1, cols=len(headers))
    t.style = "Table Grid"
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    for i, h in enumerate(headers):
        c = t.rows[0].cells[i]
        c.text = ""
        _font(c.paragraphs[0].add_run(h), 9, True, INK)
        c.paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.CENTER
        _shade(c, HEAD_FILL)
    for row in rows:
        cells = t.add_row().cells
        for i, v in enumerate(row):
            cells[i].text = ""
            _font(cells[i].paragraphs[0].add_run("" if v is None else str(v)), 9, False, INK)
    if widths:
        t.autofit = False
        for i, w in enumerate(widths):
            t.columns[i].width = Cm(w)
        for row in t.rows:
            for i, w in enumerate(widths):
                row.cells[i].width = Cm(w)
    doc.add_paragraph().paragraph_format.space_after = Pt(2)
    return t


def build_docx(c: dict, project: dict, rec: dict) -> bytes:
    data = c.get("_data", {})
    p, k = data.get("project", {}), data.get("kpi", {})
    doc = Document()
    sec = doc.sections[0]
    sec.page_height, sec.page_width = Cm(29.7), Cm(21.0)
    sec.left_margin = sec.right_margin = Cm(2.0)
    sec.top_margin = sec.bottom_margin = Cm(2.0)
    st = doc.styles["Normal"]
    st.font.name = FONT
    st.element.get_or_add_rPr().get_or_add_rFonts().set(qn("w:eastAsia"), FONT)
    st.font.size = Pt(10.5)

    # 머리말
    hp = sec.header.paragraphs[0]
    _font(hp.add_run(f"{project.get('name', '')}  |  일정 지연 대책 보고서"), 8, False, MUTED)
    hp.alignment = WD_ALIGN_PARAGRAPH.RIGHT

    # 표지 블록
    tag = doc.add_paragraph()
    _font(tag.add_run("SCHEDULE RECOVERY REPORT"), 9, True, CLAY)
    title = doc.add_paragraph()
    _font(title.add_run(c.get("title") or "일정 지연 대책 보고서"), 22, True, INK, SERIF)
    title.paragraph_format.space_after = Pt(4)
    meta = (f"작성일 {str(rec.get('created_at', ''))[:10]}   ·   진척 기준일 {p.get('status_date') or '-'}   ·   "
            f"작성 {rec.get('source', '')}{' 초안' if rec.get('source') else ''}")
    _para(doc, meta, 9, color=MUTED, space_after=10)

    # 핵심 메시지 박스
    box = doc.add_table(rows=1, cols=1)
    cell = box.rows[0].cells[0]
    _shade(cell, "F5EDE4")
    cell.text = ""
    _font(cell.paragraphs[0].add_run("핵심 메시지"), 9, True, CLAY)
    pp = cell.add_paragraph()
    _font(pp.add_run(c.get("headline", "")), 12, True, INK)
    pp.paragraph_format.space_after = Pt(4)
    doc.add_paragraph()

    n = 0

    def H(text):
        nonlocal n
        n += 1
        _heading(doc, ["Ⅰ", "Ⅱ", "Ⅲ", "Ⅳ", "Ⅴ", "Ⅵ", "Ⅶ", "Ⅷ", "Ⅸ", "Ⅹ"][n - 1], text)

    H("핵심 요약")
    for s in c.get("summary", []):
        _para(doc, s, bullet=True)

    H("일정 현황")
    fv = k.get("finish_var_days")
    _table(doc, ["구분", "기준선 완료일", "예측 완료일", "완료일 차이", "계획 공정률", "실적 공정률", "SPI"],
           [["프로젝트", p.get("baseline_finish") or "-", p.get("forecast_finish") or "-",
             "-" if fv is None else (f"+{fv}일 지연" if fv > 0 else f"{fv}일"),
             "-" if k.get("planned_pct") is None else f"{k['planned_pct']}%",
             f"{k.get('actual_pct', 0)}%", k.get("spi") if k.get("spi") is not None else "-"]],
           [2.2, 2.6, 2.6, 2.4, 2.2, 2.2, 1.6])
    for s in c.get("status", []):
        _para(doc, s, bullet=True)

    delayed = data.get("delayed_tasks", [])
    if delayed:
        H("지연 작업 상세")
        _table(doc, ["ID", "작업명", "기준선 완료", "예측 완료", "지연(일)", "계획/실적", "주공정"],
               [[d["id"], d["name"], d.get("baseline_finish") or "-", d.get("forecast_finish") or "-",
                 d.get("finish_var_days") if d.get("finish_var_days") is not None else "-",
                 f"{d.get('planned_pct') if d.get('planned_pct') is not None else '-'}% / {d.get('actual_pct')}%",
                 "●" if d.get("critical") else ""] for d in delayed],
               [1.0, 5.2, 2.4, 2.4, 1.6, 2.4, 1.4])

    H("지연 원인 분석")
    _table(doc, ["구분", "원인", "근거", "영향"],
           [[x.get("area"), x.get("cause"), x.get("evidence"), x.get("impact")] for x in c.get("causes", [])],
           [2.2, 5.0, 5.0, 4.6])

    H("만회 대책")
    _table(doc, ["대상 작업", "기법", "실행 내용", "담당", "기한", "만회(일)", "비용·리스크"],
           [[x.get("task"), x.get("method"), x.get("action"), x.get("owner"), x.get("due"),
             x.get("recovery_days"), x.get("cost_impact")] for x in c.get("countermeasures", [])],
           [3.0, 2.4, 4.4, 1.6, 2.0, 1.2, 2.4])

    if c.get("recovery_plan"):
        H("만회 일정 계획")
        _table(doc, ["단계", "기간", "확인 지표·마일스톤"],
               [[x.get("step"), x.get("period"), x.get("milestone")] for x in c["recovery_plan"]], [4.5, 3.5, 9.0])

    if c.get("risks"):
        H("리스크 및 대응")
        _table(doc, ["리스크", "가능성", "대응"],
               [[x.get("risk"), x.get("probability"), x.get("response")] for x in c["risks"]], [6.5, 1.8, 8.7])

    if c.get("requests"):
        H("의사결정·지원 요청 사항")
        for s in c["requests"]:
            _para(doc, s, bullet=True)

    H("결론")
    _para(doc, c.get("conclusion", ""))

    crit = data.get("critical_path", [])
    if crit:
        _para(doc, "", space_after=2)
        _para(doc, "[참고] 주공정 작업 목록", 9.5, True, MUTED)
        _table(doc, ["ID", "작업명", "시작", "완료", "기간", "진척률"],
               [[x["id"], x["name"], x["start"], x["finish"], x["duration"], f"{x['pct']}%"] for x in crit],
               [1.0, 7.0, 2.6, 2.6, 1.4, 1.6])
    if rec.get("notes"):
        _para(doc, "[참고] 현장 메모: " + rec["notes"], 9, color=MUTED)
    _para(doc, "※ 본 보고서는 일정 데이터 기반 " + ("AI " if rec.get("source") not in ("규칙 기반", None) else "")
          + "초안이며, 담당자 검토 후 확정하십시오.", 8.5, color=MUTED, align=WD_ALIGN_PARAGRAPH.RIGHT)

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()
