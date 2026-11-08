/* 작업표 + 간트 차트 (의존 라이브러리 없음) */
(function () {
  "use strict";
  const CFG = window.PLANNER;
  const API = `/api/p/${CFG.pid}`;
  const C = {
    ink: "#1F1E1D", muted: "#73726C", line: "#E6E1D6", line2: "#D9D2C4", cream: "#F5F0E8", off: "#F4F1EA",
    clay: "#D97757", clayDeep: "#C15F3C", sky: "#6A9BCC", skyDeep: "#4F7FAE", olive: "#788C5D",
    base: "#C9C1B3", red: "#B3261E",
  };
  const ROW = 30, HEAD = 48;
  const SCALE = { day: 26, week: 9, month: 3.2 };
  const DAY = 86400000;

  let data = null;        // 서버 계산 결과
  let rows = [];          // 편집 중인 작업 목록 (서버 순서)
  let sel = -1;           // 선택 행 index
  let scale = "week";
  let mode = CFG.mode;
  const collapsed = new Set();
  let saving = Promise.resolve();

  const $ = (s, el = document) => el.querySelector(s);
  const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const toast = (msg, err) => {
    const t = $("#toast"); t.textContent = msg; t.className = "toast show" + (err ? " err" : "");
    clearTimeout(t._h); t._h = setTimeout(() => (t.className = "toast"), err ? 4200 : 1800);
  };
  const pd = (s) => (s ? new Date(s + "T00:00:00") : null);
  const iso = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
  const md = (s) => (s ? `${+s.slice(5, 7)}/${+s.slice(8, 10)}` : "");
  const kd = (s) => (s ? `${s.slice(2, 4)}.${s.slice(5, 7)}.${s.slice(8, 10)}` : "");

  // ------------------------------------------------------------ 서버 통신
  async function load() {
    const r = await fetch(API);
    apply(await r.json());
  }

  function apply(d) {
    data = d;
    rows = d.tasks.map((t) => ({ ...t }));
    if (sel >= rows.length) sel = rows.length - 1;
    render();
  }

  function payload() {
    return rows.map((t) => ({
      id: t.id || null, level: t.level, name: t.name, duration: t.duration,
      constraint_start: t.constraint_start, actual_start: t.actual_start, actual_finish: t.actual_finish,
      pct: t.pct, predecessors: t.predecessors, resources: t.resources, notes: t.notes,
    }));
  }

  function save() {
    const focus = document.activeElement && document.activeElement.dataset ? { ...document.activeElement.dataset } : null;
    saving = saving.then(async () => {
      const r = await fetch(`${API}/tasks`, {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ tasks: payload() }),
      });
      const d = await r.json();
      if (!r.ok) { toast(d.error || "저장 실패", true); await load(); return; }
      apply(d);
      toast("저장·재계산 완료");
      setTimeout(() => {
        const f2 = document.activeElement && document.activeElement.dataset;
        const target = f2 && f2.f ? f2 : focus;
        if (target && target.f) {
          const el = $(`#grid [data-i="${target.i}"][data-f="${target.f}"]`);
          if (el) el.focus();
        }
      }, 0);
    });
    return saving;
  }

  async function post(path, body) {
    const r = await fetch(`${API}/${path}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body || {}) });
    apply(await r.json());
  }

  // ------------------------------------------------------------ 구조 편집
  const isSummaryAt = (i) => i + 1 < rows.length && rows[i + 1].level > rows[i].level;
  function blockEnd(i) { let j = i + 1; while (j < rows.length && rows[j].level > rows[i].level) j++; return j; }

  // 행 번호(ID)가 바뀔 때 선행작업 문자열을 새 번호로 바꿔 준다.
  function renumber(oldOrder) {
    const map = {};
    rows.forEach((t, i) => { if (t._k !== undefined) map[t._k] = i + 1; });
    rows.forEach((t) => {
      if (!t.predecessors) return;
      t.predecessors = t.predecessors.split(",").map((s) => s.trim()).filter(Boolean).map((tok) => {
        const m = tok.match(/^(\d+)(.*)$/); if (!m) return tok;
        const n = map[oldOrder[+m[1] - 1]];
        return n ? n + m[2] : null;
      }).filter(Boolean).join(", ");
    });
  }
  function withRenumber(fn) {
    rows.forEach((t, i) => (t._k = i));
    const old = rows.map((t) => t._k);
    fn();
    renumber(old);
    rows.forEach((t) => delete t._k);
  }

  const actions = {
    add() {
      withRenumber(() => {
        const at = sel >= 0 ? sel + 1 : rows.length;
        const lvl = sel >= 0 ? (isSummaryAt(sel) ? rows[sel].level + 1 : rows[sel].level) : 1;
        rows.splice(at, 0, { id: null, level: lvl, name: "새 작업", duration: 1, pct: 0, predecessors: "", resources: "", notes: "" });
        sel = at;
      });
      save().then(() => { const el = $(`#grid [data-i="${sel}"][data-f="name"]`); if (el) { el.focus(); el.select(); } });
    },
    del() {
      if (sel < 0) return;
      const end = blockEnd(sel);
      if (end - sel > 1 && !confirm(`요약 작업과 하위 작업 ${end - sel - 1}개를 함께 삭제할까요?`)) return;
      withRenumber(() => { rows.splice(sel, end - sel); sel = Math.min(sel, rows.length - 1); });
      save();
    },
    indent() {
      if (sel <= 0) return;
      if (rows[sel].level > rows[sel - 1].level) return;
      const end = blockEnd(sel);
      for (let j = sel; j < end; j++) rows[j].level++;
      save();
    },
    outdent() {
      if (sel < 0 || rows[sel].level <= 1) return;
      const end = blockEnd(sel);
      for (let j = sel; j < end; j++) rows[j].level--;
      save();
    },
    up() {
      if (sel <= 0) return;
      withRenumber(() => { [rows[sel - 1], rows[sel]] = [rows[sel], rows[sel - 1]]; sel--; });
      save();
    },
    down() {
      if (sel < 0 || sel >= rows.length - 1) return;
      withRenumber(() => { [rows[sel + 1], rows[sel]] = [rows[sel], rows[sel + 1]]; sel++; });
      save();
    },
    link() {
      if (sel <= 0) return;
      const preds = (rows[sel].predecessors || "").split(",").map((s) => s.trim()).filter(Boolean);
      if (!preds.some((p) => parseInt(p) === sel)) preds.push(String(sel));
      rows[sel].predecessors = preds.join(", ");
      save();
    },
    unlink() { if (sel >= 0) { rows[sel].predecessors = ""; save(); } },
    async baseline() {
      if (data.baseline_finish && !confirm("기존 기준선을 현재 일정으로 덮어쓸까요?")) return;
      await post("baseline"); toast("기준선을 저장했습니다");
    },
    async clearbase() { if (confirm("기준선을 지울까요?")) { await post("baseline", { clear: true }); toast("기준선을 지웠습니다"); } },
    today() { scrollToDate(data.status_date || iso(new Date())); },
    compact() { compact = !compact; document.querySelector('[data-act="compact"]').textContent = compact ? "표 펼치기" : "표 접기"; render(); },
  };

  // ------------------------------------------------------------ 작업표
  const COLS = {
    entry: [
      { f: "row", h: "ID", w: 40 },
      { f: "ind", h: "", w: 26 },
      { f: "name", h: "작업명", w: 220, edit: "text" },
      { f: "duration", h: "기간", w: 58, edit: "num", fmt: (t) => (t.summary ? t.forecast_duration : t.duration) + "일" },
      { f: "start", h: "시작", w: 118, edit: "date", wide: 1 },
      { f: "finish", h: "완료", w: 80, fmt: (t) => kd(t.finish) },
      { f: "predecessors", h: "선행작업", w: 80, edit: "text", wide: 1 },
      { f: "resources", h: "자원 이름", w: 150, edit: "text", wide: 1 },
      { f: "pct", h: "진척률", w: 62, edit: "num", fmt: (t) => t.pct + "%" },
    ],
    tracking: [
      { f: "row", h: "ID", w: 40 },
      { f: "ind", h: "", w: 26 },
      { f: "name", h: "작업명", w: 220, edit: "text" },
      { f: "actual_start", h: "실제 시작", w: 118, edit: "date", wide: 1 },
      { f: "actual_finish", h: "실제 완료", w: 118, edit: "date" },
      { f: "pct", h: "진척률", w: 62, edit: "num", fmt: (t) => t.pct + "%" },
      { f: "planned_pct", h: "계획%", w: 58, wide: 1, fmt: (t) => (t.planned_pct == null ? "-" : t.planned_pct + "%") },
      { f: "baseline_finish", h: "기준선 완료", w: 84, wide: 1, fmt: (t) => kd(t.baseline_finish) || "-" },
      { f: "finish", h: "예측 완료", w: 84, fmt: (t) => kd(t.finish) },
      { f: "finish_var", h: "차이", w: 52, fmt: (t) => (t.finish_var == null ? "-" : (t.finish_var > 0 ? "+" : "") + t.finish_var + "일") },
    ],
  };

  function visible() {
    const out = [];
    let hideBelow = null;
    rows.forEach((t, i) => {
      if (hideBelow !== null) { if (t.level > hideBelow) return; hideBelow = null; }
      out.push(i);
      if (t.summary && collapsed.has(t.id)) hideBelow = t.level;
    });
    return out;
  }

  function indicator(t) {
    if (t.status === "완료") return `<span title="완료" style="color:${C.olive}">✓</span>`;
    if (t.status === "지연") return `<span title="지연: 기준선보다 ${t.finish_var}일 늦음" style="color:${C.red}">●</span>`;
    if (t.status === "주의") return `<span title="계획 진척률 대비 부진" style="color:#C98A1B">●</span>`;
    if (t.constraint_start && !t.summary) return `<span title="시작 제한: ${t.constraint_start} 이후" style="color:${C.muted}">▣</span>`;
    if (t.notes) return `<span title="${esc(t.notes)}" style="color:${C.muted}">✎</span>`;
    return "";
  }

  let compact = false;
  function renderGrid(vis) {
    const cols = COLS[mode].filter((c) => !(compact && c.wide));
    let h = "<colgroup>" + cols.map((c) => `<col style="width:${c.w}px">`).join("") + "</colgroup>";
    h += "<thead><tr>" + cols.map((c) => `<th>${c.h}</th>`).join("") + "</tr></thead><tbody>";
    vis.forEach((i) => {
      const t = rows[i];
      const cls = [t.summary ? "summary" : "", t.critical && !t.summary ? "crit" : "", i === sel ? "sel" : ""].join(" ");
      h += `<tr class="${cls}" data-row="${i}">`;
      cols.forEach((c) => {
        if (c.f === "row") { h += `<td class="id" data-sel="${i}">${t.row}</td>`; return; }
        if (c.f === "ind") { h += `<td><div class="cell ind">${indicator(t)}</div></td>`; return; }
        const ro = !c.edit || (t.summary && ["duration", "start", "pct", "actual_start", "actual_finish", "resources"].includes(c.f));
        let val = c.f === "start" ? (t.summary ? kd(t.start) : t.start) : t[c.f];
        if (c.f === "name") {
          const pad = (t.level - 1) * 16;
          const tog = t.summary ? `<span class="tog" data-tog="${t.id}">${collapsed.has(t.id) ? "▶" : "▼"}</span>` : `<span class="tog"></span>`;
          h += `<td class="namecol"><div class="name-wrap" style="padding-left:${pad}px">${tog}<input class="cell" data-i="${i}" data-f="name" value="${esc(t.name)}" title="${esc(t.name)}"></div></td>`;
          return;
        }
        if (ro) { h += `<td class="ro"><div class="cell${c.f === "finish_var" && t.finish_var > 0 ? "\" style=\"color:" + C.red + ";font-weight:600" : ""}">${esc(c.fmt ? c.fmt(t) : val ?? "")}</div></td>`; return; }
        const type = c.edit === "date" ? "date" : (c.edit === "num" ? "number" : "text");
        const extra = c.edit === "num" ? ` min="0" ${c.f === "pct" ? 'max="100" step="5"' : 'step="1"'}` : "";
        h += `<td><input class="cell" type="${type}"${extra} data-i="${i}" data-f="${c.f}" value="${esc(val ?? "")}"></td>`;
      });
      h += "</tr>";
    });
    h += "</tbody>";
    $("#grid").innerHTML = h;
  }

  // ------------------------------------------------------------ 간트 차트
  function range() {
    let s = pd(data.project_start), e = pd(data.project_finish);
    rows.forEach((t) => {
      [t.start, t.baseline_start].forEach((v) => { const d = pd(v); if (d && d < s) s = d; });
      [t.finish, t.baseline_finish].forEach((v) => { const d = pd(v); if (d && d > e) e = d; });
    });
    if (data.status_date) { const d = pd(data.status_date); if (d > e) e = d; }
    s = new Date(s.getTime() - (scale === "month" ? 15 : 3) * DAY);
    if (scale !== "day") s = new Date(s.getTime() - ((s.getDay() + 6) % 7) * DAY);
    if (scale === "month") s = new Date(s.getFullYear(), s.getMonth(), 1);
    e = new Date(e.getTime() + (scale === "month" ? 45 : scale === "week" ? 21 : 10) * DAY);
    return [s, e];
  }

  function renderChart(vis) {
    const [s, e] = range();
    const px = SCALE[scale];
    const days = Math.round((e - s) / DAY) + 1;
    const W = Math.max(days * px, 400);
    const H = HEAD + vis.length * ROW + 40;
    const x = (d) => Math.round(((typeof d === "string" ? pd(d) : d) - s) / DAY * px);
    const holidays = new Set(data.holidays);
    const yOf = {};
    vis.forEach((i, k) => (yOf[rows[i].id] = HEAD + k * ROW));
    const p = [], ph = [];
    p.push(`<svg xmlns="http://www.w3.org/2000/svg" width="${W}" height="${H - HEAD}" font-size="11"><g transform="translate(0,${-HEAD})">`);
    p.push(`<defs><marker id="ah" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="7" markerHeight="7" orient="auto"><path d="M0,0L8,4L0,8z" fill="${C.muted}"/></marker>
      <marker id="ahc" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="7" markerHeight="7" orient="auto"><path d="M0,0L8,4L0,8z" fill="${C.clayDeep}"/></marker>
      <pattern id="hatch" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><rect width="6" height="6" fill="#F6F3EC"/><line x1="0" y1="0" x2="0" y2="6" stroke="#ECE6DA" stroke-width="2"/></pattern></defs>`);
    // 비작업일 음영
    if (scale !== "month") {
      for (let k = 0; k < days; k++) {
        const d = new Date(s.getTime() + k * DAY);
        const off = (data.skip_weekends && (d.getDay() === 0 || d.getDay() === 6)) || holidays.has(iso(d));
        if (off) p.push(`<rect x="${k * px}" y="${HEAD}" width="${px}" height="${H - HEAD}" fill="${holidays.has(iso(d)) ? "url(#hatch)" : C.off}"/>`);
      }
    }
    // 행 줄
    vis.forEach((i, k) => {
      const y = HEAD + k * ROW;
      if (i === sel) p.push(`<rect x="0" y="${y}" width="${W}" height="${ROW}" fill="#FBEEE7" opacity=".7"/>`);
      p.push(`<line x1="0" x2="${W}" y1="${y + ROW - 0.5}" y2="${y + ROW - 0.5}" stroke="${C.line}"/>`);
    });
    // 머리글 (2단)
    ph.push(`<rect x="0" y="0" width="${W}" height="${HEAD}" fill="${C.cream}"/><line x1="0" x2="${W}" y1="${HEAD - .5}" y2="${HEAD - .5}" stroke="${C.line2}"/><line x1="0" x2="${W}" y1="24.5" y2="24.5" stroke="${C.line}"/>`);
    const tick = (xx, y1, y2) => {
      ph.push(`<line x1="${xx + .5}" x2="${xx + .5}" y1="${y1}" y2="${Math.min(y2, HEAD)}" stroke="${C.line}"/>`);
      if (y2 > HEAD) p.push(`<line x1="${xx + .5}" x2="${xx + .5}" y1="${HEAD}" y2="${y2}" stroke="${C.line}"/>`);
    };
    for (let k = 0; k < days; k++) {
      const d = new Date(s.getTime() + k * DAY), xx = k * px;
      const first = d.getDate() === 1 || k === 0;
      if (scale === "month") {
        if (first && !(k === 0 && d.getDate() > 1)) { tick(xx, 0, H); ph.push(`<text x="${xx + 5}" y="16" fill="${C.ink}" font-weight="600">${d.getFullYear()}</text><text x="${xx + 5}" y="40" fill="${C.muted}">${d.getMonth() + 1}월</text>`); }
      } else if (scale === "week") {
        if (first && !(k === 0 && d.getDate() > 24)) { tick(xx, 0, 24); ph.push(`<text x="${xx + 5}" y="16" fill="${C.ink}" font-weight="600">${d.getFullYear()}.${String(d.getMonth() + 1).padStart(2, "0")}</text>`); }
        if (d.getDay() === 1) { tick(xx, 24, H); ph.push(`<text x="${xx + 4}" y="40" fill="${C.muted}">${d.getMonth() + 1}/${d.getDate()}</text>`); }
      } else {
        if (first && !(k === 0 && d.getDate() > 28)) { tick(xx, 0, 24); ph.push(`<text x="${xx + 5}" y="16" fill="${C.ink}" font-weight="600">${d.getFullYear()}.${String(d.getMonth() + 1).padStart(2, "0")}</text>`); }
        tick(xx, 24, d.getDay() === 1 ? H : HEAD);
        ph.push(`<text x="${xx + px / 2}" y="40" text-anchor="middle" fill="${d.getDay() === 0 ? C.red : C.muted}">${d.getDate()}</text>`);
      }
    }
    // 연결선
    const visIds = new Set(vis.map((i) => rows[i].id));
    const byId = Object.fromEntries(rows.map((t) => [t.id, t]));
    data.links.forEach((l) => {
      if (!visIds.has(l.pred) || !visIds.has(l.succ)) return;
      const a = byId[l.pred], b = byId[l.succ];
      const crit = a.critical && b.critical;
      const ay = yOf[a.id] + ROW / 2, by = yOf[b.id] + ROW / 2;
      const aEnd = x(a.finish) + (a.milestone ? 0 : px), aStart = x(a.start);
      const bStart = x(b.start), bEnd = x(b.finish) + (b.milestone ? 0 : px);
      const fromX = l.type === "SS" || l.type === "SF" ? aStart : aEnd;
      const toEnd = l.type === "FF" || l.type === "SF";
      const toX = toEnd ? bEnd : bStart;
      let path;
      if (!toEnd && toX - fromX >= 10) {
        path = `M${fromX},${ay} H${toX + 4} V${by + (by > ay ? -9 : 9)}`;
      } else {
        const dx = l.type === "SS" ? -8 : 8;
        const midY = by > ay ? yOf[b.id] - 2 : yOf[b.id] + ROW + 2;
        const lastX = toEnd ? toX + 8 : toX - 8;
        path = `M${fromX},${ay} h${dx} V${midY} H${lastX} V${by} H${toEnd ? toX + 2 : toX - 2}`;
      }
      p.push(`<path d="${path}" fill="none" stroke="${crit ? C.clayDeep : C.muted}" stroke-width="${crit ? 1.4 : 1}" marker-end="url(#${crit ? "ahc" : "ah"})" opacity=".85"/>`);
    });
    // 막대
    vis.forEach((i) => {
      const t = rows[i], y = yOf[t.id];
      const x1 = x(t.start), x2 = x(t.finish) + px;
      const tip = `${t.row}. ${t.name}\n${t.start} ~ ${t.finish} (${t.forecast_duration}일)\n진척 ${t.pct}% · 총여유 ${t.total_float}일${t.critical ? " · 주공정" : ""}` +
        (t.baseline_finish ? `\n기준선 ${t.baseline_start} ~ ${t.baseline_finish} (차이 ${t.finish_var > 0 ? "+" : ""}${t.finish_var}일)` : "");
      p.push(`<g class="gbar" data-sel="${i}"><title>${esc(tip)}</title>`);
      const showBase = t.baseline_start && (mode === "tracking" || !t.summary);
      if (showBase && !t.summary) {
        const bx1 = x(t.baseline_start), bx2 = x(t.baseline_finish) + (t.baseline_duration ? px : 0);
        if (t.baseline_duration) p.push(`<rect x="${bx1}" y="${y + 20}" width="${Math.max(bx2 - bx1, 2)}" height="5" rx="1.5" fill="${C.base}"/>`);
        else p.push(`<path d="M${bx1},${y + 18} l4,4 -4,4 -4,-4z" fill="${C.base}"/>`);
      }
      if (t.milestone) {
        const mx = x(t.start) + px;
        p.push(`<path d="M${mx},${y + 6} l8,8 -8,8 -8,-8z" fill="${t.critical ? C.clayDeep : C.ink}"/>`);
        p.push(`<text x="${mx + 12}" y="${y + 18}" fill="${C.ink}">${md(t.start)}</text>`);
      } else if (t.summary) {
        const yy = y + (mode === "tracking" ? 7 : 9);
        p.push(`<rect x="${x1}" y="${yy}" width="${Math.max(x2 - x1, 2)}" height="6" fill="${C.ink}"/>`);
        p.push(`<path d="M${x1},${yy} v11 l5,-5z M${x2},${yy} v11 l-5,-5z" fill="${C.ink}"/>`);
        if (t.pct > 0) p.push(`<rect x="${x1}" y="${yy + 1.5}" width="${(x2 - x1) * t.pct / 100}" height="3" fill="${C.olive}"/>`);
      } else {
        const hgt = mode === "tracking" || t.baseline_start ? 13 : 16;
        const yy = y + (hgt === 13 ? 5 : 7);
        const fill = t.pct >= 100 ? C.olive : t.critical ? C.clay : C.sky;
        p.push(`<rect x="${x1}" y="${yy}" width="${Math.max(x2 - x1, 3)}" height="${hgt}" rx="3" fill="${fill}"/>`);
        if (t.pct > 0 && t.pct < 100) p.push(`<rect x="${x1}" y="${yy + hgt / 2 - 2}" width="${(x2 - x1) * t.pct / 100}" height="4" rx="1" fill="${C.ink}" opacity=".75"/>`);
        const lab = t.resources || "";
        if (lab) p.push(`<text x="${x2 + 6}" y="${y + 19}" fill="${C.muted}">${esc(lab)}</text>`);
      }
      p.push(`</g>`);
    });
    // 진척 기준일 · 오늘
    const today = iso(new Date());
    if (pd(today) >= s && pd(today) <= e) p.push(`<line x1="${x(today) + .5}" x2="${x(today) + .5}" y1="${HEAD}" y2="${H}" stroke="${C.sky}" stroke-dasharray="2 3"/>`);
    if (data.status_date) {
      const sx = x(data.status_date) + px;
      p.push(`<line x1="${sx}" x2="${sx}" y1="${HEAD}" y2="${H}" stroke="${C.red}" stroke-width="1.5" stroke-dasharray="5 3"/>`);
      ph.push(`<line x1="${sx}" x2="${sx}" y1="${HEAD - 6}" y2="${HEAD}" stroke="${C.red}" stroke-width="1.5"/><rect x="${sx - 30}" y="${HEAD - 20}" width="60" height="14" rx="7" fill="${C.red}"/><text x="${sx}" y="${HEAD - 10}" fill="#fff" font-size="10" text-anchor="middle">진척 기준일</text>`);
    }
    p.push("</g></svg>");
    const head = `<svg xmlns="http://www.w3.org/2000/svg" width="${W}" height="${HEAD}" font-size="11">${ph.join("")}</svg>`;
    $("#chart").innerHTML = `<div class="chart-head">${head}</div>` + p.join("");
    $("#chart")._x = x;
  }

  function scrollToDate(dstr) {
    const fn = $("#chart")._x; if (!fn) return;
    const split = $("#split");
    split.scrollLeft = Math.max(0, fn(dstr) - 200);
  }

  // ------------------------------------------------------------ KPI · 상세
  function renderKpis() {
    const k = data.kpi;
    const fv = k.finish_var;
    $("#kpis").innerHTML = [
      `시작<b>${kd(data.project_start)}</b>`,
      `예측 완료<b>${kd(data.project_finish)}</b>`,
      `기준선 완료<b>${data.baseline_finish ? kd(data.baseline_finish) : "미저장"}</b>`,
      `완료일 차이<b class="${fv > 0 ? "hot" : ""}">${fv == null ? "-" : (fv > 0 ? "+" : "") + fv + "일"}</b>`,
      `공기<b>${k.duration}작업일</b>`,
      `실적/계획 공정률<b>${k.actual_pct}% / ${k.planned_pct == null ? "-" : k.planned_pct + "%"}</b>`,
      `SPI<b class="${k.spi != null && k.spi < 0.9 ? "hot" : ""}">${k.spi ?? "-"}</b>`,
      `주공정<b>${k.critical_count}</b>`, `지연<b class="${k.delayed ? "hot" : ""}">${k.delayed}</b>`,
      `총비용<b>${(k.total_cost || 0).toLocaleString()}원</b>`,
      `<span class="legend"><span><i style="background:${C.clay}"></i>주공정</span><span><i style="background:${C.sky}"></i>일반</span><span><i style="background:${C.olive}"></i>완료</span><span><i style="background:${C.base};height:4px"></i>기준선</span></span>`,
    ].map((s) => `<span>${s}</span>`).join("");
  }

  function renderDetail() {
    const el = $("#detail");
    if (sel < 0 || !rows[sel]) { el.innerHTML = `<div class="k" style="grid-column:1/-1">행을 선택하면 작업 상세(가장 이른/늦은 일정, 여유, 기준선)가 표시됩니다. 선행작업 입력 예: <b>3</b>, <b>5SS+2</b>, <b>7FF-1</b> · 자원 입력 예: <b>전기엔지니어[50%], 시공업체</b></div>`; return; }
    const t = rows[sel];
    const cell = (k, v) => `<div><div class="k">${k}</div><div class="v">${v}</div></div>`;
    el.innerHTML = [
      cell("WBS · 상태", `${t.wbs} · <span class="badge ${t.status}">${t.status}</span>${t.critical ? ' <span class="badge crit">주공정</span>' : ""}`),
      cell("가장 이른 시작/완료", `${kd(t.start)} ~ ${kd(t.finish)}`),
      cell("가장 늦은 시작/완료", `${kd(t.late_start)} ~ ${kd(t.late_finish)}`),
      cell("총여유 · 자유여유", `${t.total_float}일 · ${t.free_float}일`),
      cell("기준선", t.baseline_start ? `${kd(t.baseline_start)} ~ ${kd(t.baseline_finish)}` : "-"),
      cell("시작 제한 · 비용", `${t.summary ? "-" : `<input type="date" data-i="${sel}" data-f="constraint_start" value="${t.constraint_start || ""}" style="height:22px;font-size:11px;border:1px solid #D9D2C4;border-radius:4px">`} · ${t.cost.toLocaleString()}원`),
      `<div><div class="k">메모</div><textarea data-i="${sel}" data-f="notes" placeholder="작업 메모(지연 원인 등)">${esc(t.notes)}</textarea></div>`,
    ].join("");
  }

  function render() {
    const vis = visible();
    renderGrid(vis);
    renderChart(vis);
    renderKpis();
    renderDetail();
    $("#statusDate").value = data.status_date || "";
  }

  function select(i) {
    if (i === sel) return;
    sel = i;
    document.querySelectorAll("#grid tr.sel").forEach((r) => r.classList.remove("sel"));
    const tr = $(`#grid tr[data-row="${i}"]`); if (tr) tr.classList.add("sel");
    renderChart(visible());
    renderDetail();
  }

  // ------------------------------------------------------------ 이벤트
  function onEdit(e) {
    const el = e.target; const i = +el.dataset.i, f = el.dataset.f;
    if (!f || !rows[i]) return;
    let v = el.value;
    if (f === "duration") v = Math.max(0, parseFloat(v.replace(/[^\d.]/g, "")) || 0);
    if (f === "pct") v = Math.min(100, Math.max(0, parseFloat(v) || 0));
    if (f === "start") { rows[i].constraint_start = v || null; }
    else if (["actual_start", "actual_finish", "constraint_start"].includes(f)) rows[i][f] = v || null;
    else rows[i][f] = v;
    if (f === "actual_finish" && v) rows[i].pct = 100;
    if (f === "pct" && v >= 100 && !rows[i].actual_finish && mode === "tracking") rows[i].actual_finish = rows[i].finish;
    save();
  }
  document.addEventListener("change", (e) => { if (e.target.closest("#grid, #detail") && e.target.dataset.f) onEdit(e); });
  $("#grid").addEventListener("focusin", (e) => { const i = e.target.dataset.i; if (i !== undefined) select(+i); });
  $("#grid").addEventListener("click", (e) => {
    const tg = e.target.closest("[data-tog]");
    if (tg) { const id = +tg.dataset.tog; collapsed.has(id) ? collapsed.delete(id) : collapsed.add(id); render(); return; }
    const s = e.target.closest("[data-sel]"); if (s) select(+s.dataset.sel);
  });
  $("#grid").addEventListener("keydown", (e) => {
    const el = e.target; if (!el.dataset.f) return;
    if (e.key === "Enter") { el.blur(); const nx = $(`#grid [data-i="${+el.dataset.i + 1}"][data-f="${el.dataset.f}"]`); if (nx) setTimeout(() => nx.focus(), 0); }
    if (e.altKey && e.key === "ArrowRight") { e.preventDefault(); actions.indent(); }
    if (e.altKey && e.key === "ArrowLeft") { e.preventDefault(); actions.outdent(); }
  });
  document.addEventListener("keydown", (e) => {
    if (e.target.tagName === "INPUT" || e.target.tagName === "TEXTAREA") return;
    if (e.key === "Insert") actions.add();
    if (e.key === "Delete") actions.del();
    if (e.key === "ArrowDown" && sel < rows.length - 1) { e.preventDefault(); select(sel + 1); }
    if (e.key === "ArrowUp" && sel > 0) { e.preventDefault(); select(sel - 1); }
  });
  $("#chart").addEventListener("click", (e) => { const g = e.target.closest("[data-sel]"); if (g) select(+g.dataset.sel); });
  document.querySelectorAll("[data-act]").forEach((b) => b.addEventListener("click", () => actions[b.dataset.act]()));
  $("#scale").addEventListener("click", (e) => {
    const b = e.target.closest("button"); if (!b) return;
    scale = b.dataset.s; document.querySelectorAll("#scale button").forEach((x) => x.classList.toggle("on", x === b));
    renderChart(visible());
  });
  $("#mode").addEventListener("click", (e) => {
    const b = e.target.closest("button"); if (!b) return;
    mode = b.dataset.m; document.querySelectorAll("#mode button").forEach((x) => x.classList.toggle("on", x === b));
    history.replaceState(null, "", mode === "tracking" ? "?mode=tracking" : location.pathname);
    document.querySelectorAll(".sidebar a").forEach((a) => {
      if (a.href.endsWith("/gantt")) a.classList.toggle("active", mode === "entry");
      if (a.href.endsWith("mode=tracking")) a.classList.toggle("active", mode === "tracking");
    });
    render();
  });
  $("#statusDate").addEventListener("change", (e) => post("status-date", { status_date: e.target.value || null }).then(() => toast("진척 기준일 반영")));

  load().then(() => scrollToDate(data.project_start));
})();
