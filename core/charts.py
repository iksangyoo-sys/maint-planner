"""Plotly 차트: 간트차트, 네트워크 다이어그램, 자원 히스토그램."""
from __future__ import annotations

from datetime import date, datetime, timedelta

import pandas as pd
import plotly.graph_objects as go

from .scheduler import DepInput, Schedule, topo_levels

C_NORMAL = "#3b82f6"
C_CRIT = "#ef4444"
C_SUMMARY = "#334155"
C_DONE = "#0f172a"
C_BASE = "#94a3b8"
C_MILE = "#f59e0b"
DAY_MS = 24 * 3600 * 1000


def _dt(d: date) -> datetime:
    return datetime(d.year, d.month, d.day)


def gantt(
    sched: Schedule,
    deps: list[DepInput],
    *,
    show_critical: bool = True,
    show_deps: bool = True,
    show_baseline: bool = False,
    show_progress: bool = True,
    baseline: dict[int, tuple[date | None, date | None]] | None = None,
    status_date: date | None = None,
    collapse_levels: int | None = None,
) -> go.Figure:
    ids = [i for i in sched.order if collapse_levels is None or sched.tasks[i].level <= collapse_levels]
    labels = {i: f"{sched.tasks[i].wbs}  {sched.tasks[i].name}" for i in ids}
    ylabels = [labels[i] for i in ids]
    fig = go.Figure()

    def bar_trace(sel, color, name, width=0.6, x_fn=None, base_fn=None, hover=True, opacity=1.0):
        if not sel:
            return
        t = [sched.tasks[i] for i in sel]
        fig.add_trace(go.Bar(
            y=[labels[i] for i in sel],
            x=[x_fn(k) for k in t] if x_fn else [((k.finish - k.start).days + 1) * DAY_MS for k in t],
            base=[base_fn(k) for k in t] if base_fn else [_dt(k.start) for k in t],
            orientation="h", marker_color=color, name=name, width=width, opacity=opacity,
            customdata=[[k.wbs, k.name, k.start, k.finish, k.duration, k.total_float,
                         round(k.percent_complete)] for k in t],
            hovertemplate=(
                "<b>%{customdata[0]} %{customdata[1]}</b><br>시작 %{customdata[2]|%Y-%m-%d}"
                " ~ 완료 %{customdata[3]|%Y-%m-%d}<br>기간 %{customdata[4]}일 · 총여유 %{customdata[5]}일"
                " · 진척 %{customdata[6]}%<extra></extra>"
            ) if hover else None,
            hoverinfo=None if hover else "skip",
        ))

    bars = [i for i in ids if not sched.tasks[i].is_milestone]
    summ = [i for i in bars if sched.tasks[i].is_summary]
    leaf = [i for i in bars if not sched.tasks[i].is_summary]
    crit = [i for i in leaf if show_critical and sched.tasks[i].critical]
    norm = [i for i in leaf if i not in crit]

    if show_baseline and baseline:
        bl = [i for i in ids if baseline.get(i) and baseline[i][0] and baseline[i][1]]
        if bl:
            fig.add_trace(go.Bar(
                y=[labels[i] for i in bl],
                x=[((baseline[i][1] - baseline[i][0]).days + 1) * DAY_MS for i in bl],
                base=[_dt(baseline[i][0]) for i in bl], orientation="h", width=0.25,
                marker_color=C_BASE, name="기준선(Baseline)", offset=0.18,
                hovertemplate="기준선 %{base|%Y-%m-%d} 시작<extra></extra>",
            ))

    bar_trace(summ, C_SUMMARY, "요약 작업", width=0.3)
    bar_trace(norm, C_NORMAL, "작업")
    bar_trace(crit, C_CRIT, "주공정 작업")

    if show_progress:
        prog = [i for i in leaf if sched.tasks[i].percent_complete > 0]
        bar_trace(
            prog, C_DONE, "진척", width=0.18, hover=False, opacity=0.75,
            x_fn=lambda k: ((k.finish - k.start).days + 1) * DAY_MS * k.percent_complete / 100,
        )

    miles = [i for i in ids if sched.tasks[i].is_milestone]
    if miles:
        fig.add_trace(go.Scatter(
            x=[_dt(sched.tasks[i].finish) + timedelta(hours=23) for i in miles],
            y=[labels[i] for i in miles], mode="markers", name="마일스톤",
            marker=dict(symbol="diamond", size=14, color=C_CRIT if show_critical else C_MILE,
                        line=dict(width=1, color="#000")),
            hovertemplate="<b>%{y}</b><br>%{x|%Y-%m-%d}<extra></extra>",
        ))

    if show_deps:
        shown = set(ids)
        for d in deps:
            if d.pred_id not in shown or d.succ_id not in shown:
                continue
            p, s = sched.tasks[d.pred_id], sched.tasks[d.succ_id]
            if p.is_summary or s.is_summary:
                continue
            p_end = _dt(p.finish) + timedelta(days=1)
            p_start = _dt(p.start)
            s_end = _dt(s.finish) + timedelta(days=1)
            s_start = _dt(s.start)
            x0 = p_start if d.dep_type in ("SS", "SF") else p_end
            x1 = s_end if d.dep_type in ("FF", "SF") else s_start
            if p.is_milestone:
                x0 = _dt(p.finish) + timedelta(hours=23)
            if s.is_milestone:
                x1 = _dt(s.finish) + timedelta(hours=23)
            fig.add_annotation(
                x=x1, y=labels[d.succ_id], ax=x0, ay=labels[d.pred_id],
                xref="x", yref="y", axref="x", ayref="y",
                showarrow=True, arrowhead=2, arrowsize=1, arrowwidth=1,
                arrowcolor="#64748b", opacity=0.7, text="",
            )

    if status_date:
        x = _dt(status_date) + timedelta(days=1)
        fig.add_shape(type="line", x0=x, x1=x, y0=0, y1=1, yref="paper",
                      line=dict(color="#16a34a", width=2, dash="dash"))
        fig.add_annotation(x=x, y=1.0, yref="paper", text="기준일", showarrow=False,
                           font=dict(color="#16a34a"), yanchor="bottom")

    fig.update_layout(
        barmode="overlay",
        height=max(380, 34 * len(ids) + 140),
        margin=dict(l=10, r=20, t=40, b=30),
        legend=dict(orientation="h", y=1.06, x=0),
        xaxis=dict(type="date", tickformat="%m/%d\n%a", showgrid=True, gridcolor="#e2e8f0"),
        yaxis=dict(categoryorder="array", categoryarray=list(reversed(ylabels)), automargin=True),
        plot_bgcolor="white",
        hoverlabel=dict(align="left"),
    )
    # 주말 음영
    if sched.calendar.skip_weekends and ids:
        d0 = min(sched.tasks[i].start for i in ids)
        d1 = max(sched.tasks[i].finish for i in ids)
        d = d0 - timedelta(days=d0.weekday() + 2)
        while d <= d1 + timedelta(days=7):
            fig.add_vrect(x0=_dt(d), x1=_dt(d) + timedelta(days=2), fillcolor="#f1f5f9",
                          line_width=0, layer="below")
            d += timedelta(days=7)
    return fig


def network_diagram(sched: Schedule, deps: list[DepInput]) -> go.Figure:
    """AON(Activity on Node) 네트워크. 주공정은 빨간색."""
    level = topo_levels(sched, deps)
    cols: dict[int, list[int]] = {}
    for tid in sched.leaf_ids():
        cols.setdefault(level[tid], []).append(tid)
    pos = {}
    for lv, items in cols.items():
        n = len(items)
        for k, tid in enumerate(items):
            pos[tid] = (lv, (n - 1) / 2 - k)
    fig = go.Figure()
    for d in deps:
        if d.pred_id not in pos or d.succ_id not in pos:
            continue
        (x0, y0), (x1, y1) = pos[d.pred_id], pos[d.succ_id]
        both = sched.tasks[d.pred_id].critical and sched.tasks[d.succ_id].critical
        fig.add_annotation(
            x=x1 - 0.18, y=y1, ax=x0 + 0.18, ay=y0, xref="x", yref="y", axref="x", ayref="y",
            showarrow=True, arrowhead=2, arrowwidth=2.5 if both else 1,
            arrowcolor=C_CRIT if both else "#94a3b8", text="",
        )
        if d.dep_type != "FS" or d.lag:
            lbl = d.dep_type + (f"{int(d.lag):+d}" if d.lag else "")
            fig.add_annotation(x=(x0 + x1) / 2, y=(y0 + y1) / 2, text=lbl, showarrow=False,
                               font=dict(size=10, color="#475569"), bgcolor="white")
    ids = list(pos)
    t = [sched.tasks[i] for i in ids]
    fig.add_trace(go.Scatter(
        x=[pos[i][0] for i in ids], y=[pos[i][1] for i in ids], mode="markers+text",
        marker=dict(symbol="square", size=46,
                    color=["#fee2e2" if k.critical else "#dbeafe" for k in t],
                    line=dict(width=2, color=[C_CRIT if k.critical else C_NORMAL for k in t])),
        text=[f"<b>{k.wbs}</b><br>{k.duration}일" for k in t], textfont=dict(size=11),
        customdata=[[k.name, k.es, k.ef, k.ls, k.lf, k.total_float] for k in t],
        hovertemplate=("<b>%{customdata[0]}</b><br>ES %{customdata[1]} · EF %{customdata[2]}<br>"
                       "LS %{customdata[3]} · LF %{customdata[4]}<br>총여유 %{customdata[5]}일<extra></extra>"),
        showlegend=False,
    ))
    maxn = max((len(v) for v in cols.values()), default=1)
    fig.update_layout(
        height=max(360, 90 * maxn + 80), margin=dict(l=10, r=10, t=10, b=10),
        xaxis=dict(visible=False, range=[-0.6, max(cols, default=0) + 0.6]),
        yaxis=dict(visible=False, range=[-(maxn / 2) - 0.2, maxn / 2 + 0.2]),
        plot_bgcolor="white",
    )
    return fig


def resource_histogram(load: pd.DataFrame, resource: str) -> go.Figure:
    df = load[load["자원"] == resource].sort_values("날짜")
    cap = float(df["최대"].iloc[0]) if not df.empty else 1.0
    colors = [C_CRIT if v > cap + 1e-9 else C_NORMAL for v in df["투입"]]
    fig = go.Figure(go.Bar(x=[_dt(d) for d in df["날짜"]], y=df["투입"], marker_color=colors,
                           hovertemplate="%{x|%Y-%m-%d}<br>투입 %{y}<extra></extra>", name="투입량"))
    fig.add_hline(y=cap, line_dash="dash", line_color="#16a34a", annotation_text=f"최대 {cap:g}")
    fig.update_layout(height=300, margin=dict(l=10, r=10, t=30, b=10), plot_bgcolor="white",
                      xaxis=dict(type="date", tickformat="%m/%d"), yaxis_title="투입(단위)")
    return fig
