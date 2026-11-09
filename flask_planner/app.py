"""ProjectLibre 형 일정관리 웹 — Flask 진입점.

실행:  python app.py   (기본 http://127.0.0.1:5000)
"""
from __future__ import annotations

import hmac
import io
import json
import os
from datetime import date
from pathlib import Path

from flask import (Flask, Response, abort, flash, jsonify, redirect, render_template, request,
                   send_file, url_for)

from planner import db, exports, report, service
from planner.sample import create_sample
from planner.scheduler import DEP_TYPES, ScheduleError, network_layout

BASE = Path(__file__).resolve().parent


def load_dotenv(path: Path) -> None:
    """의존성 없이 .env 파일의 KEY=VALUE 를 환경변수로 읽는다(이미 있으면 유지)."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def create_app(test_config: dict | None = None) -> Flask:
    load_dotenv(BASE / ".env")
    app = Flask(__name__)
    app.config.update(
        SECRET_KEY=os.environ.get("SECRET_KEY", "dev-only-change-me"),
        DATABASE=os.environ.get("PLANNER_DB", str(BASE / "instance" / "planner.db")),
        MAX_CONTENT_LENGTH=5 * 1024 * 1024,
    )
    if test_config:
        app.config.update(test_config)
    db.init_db(app)

    # 인터넷에 공개 배포할 때 OpenAI 키 남용을 막기 위한 선택형 비밀번호(HTTP 기본 인증).
    # 환경변수 APP_PASSWORD 가 있으면 켜지고(아이디는 APP_USER, 기본 'admin'), 없으면 꺼진다.
    app_password = os.environ.get("APP_PASSWORD", "")
    app_user = os.environ.get("APP_USER", "admin")

    @app.before_request
    def require_password():
        if not app_password or app.config.get("TESTING"):
            return None
        auth = request.authorization
        if (auth and hmac.compare_digest(auth.username or "", app_user)
                and hmac.compare_digest(auth.password or "", app_password)):
            return None
        return Response("로그인이 필요합니다.", 401,
                        {"WWW-Authenticate": 'Basic realm="planner", charset="UTF-8"'})

    @app.context_processor
    def inject():
        return {"today": date.today().isoformat(), "ai_ready": report.ai_available(),
                "ai_model": report.model_name()}

    @app.template_filter("won")
    def won(v):
        return f"{int(round(v or 0)):,}"

    @app.template_filter("kdate")
    def kdate(v):
        if not v:
            return ""
        s = v.isoformat() if hasattr(v, "isoformat") else str(v)
        y, m, d = s[:10].split("-")
        wd = "월화수목금토일"[date(int(y), int(m), int(d)).weekday()]
        return f"{y[2:]}.{m}.{d}({wd})"

    def project_or_404(pid):
        p = service.get_project(pid)
        if p is None:
            abort(404)
        return p

    # ---------------------------------------------------------- 프로젝트 목록
    @app.get("/")
    def index():
        return render_template("index.html", projects=service.list_projects())

    @app.post("/projects")
    def project_create():
        pid = service.create_project(request.form)
        flash("새 프로젝트를 만들었습니다. 작업을 추가해 보세요.", "ok")
        return redirect(url_for("gantt", pid=pid))

    @app.post("/projects/sample")
    def project_sample():
        pid = create_sample()
        flash("예제 프로젝트를 만들었습니다. 진척 기준일 현재 지연이 발생한 상태입니다.", "ok")
        return redirect(url_for("gantt", pid=pid))

    @app.post("/projects/import")
    def project_import():
        f = request.files.get("file")
        try:
            pid = service.import_json(json.load(f.stream))
        except Exception as e:  # noqa: BLE001
            flash(f"가져오기 실패: {e}", "err")
            return redirect(url_for("index"))
        flash("프로젝트를 가져왔습니다.", "ok")
        return redirect(url_for("gantt", pid=pid))

    @app.post("/p/<int:pid>/delete")
    def project_delete(pid):
        project_or_404(pid)
        service.delete_project(pid)
        flash("프로젝트를 삭제했습니다.", "ok")
        return redirect(url_for("index"))

    @app.route("/p/<int:pid>/info", methods=["GET", "POST"])
    def info(pid):
        p = project_or_404(pid)
        if request.method == "POST":
            service.update_project(pid, request.form)
            flash("프로젝트 정보를 저장했습니다.", "ok")
            return redirect(url_for("info", pid=pid))
        b = service.project_bundle(pid)
        return render_template("info.html", p=p, b=b, active="info")

    @app.get("/p/<int:pid>")
    def project_home(pid):
        return redirect(url_for("gantt", pid=pid))

    # ---------------------------------------------------------- 보기(View)
    @app.get("/p/<int:pid>/gantt")
    def gantt(pid):
        p = project_or_404(pid)
        mode = request.args.get("mode", "entry")
        return render_template("gantt.html", p=p, mode=mode, active="tracking" if mode == "tracking" else "gantt")

    @app.get("/p/<int:pid>/network")
    def network(pid):
        p = project_or_404(pid)
        b = service.project_bundle(pid)
        lay = network_layout(b["schedule"])
        return render_template("network.html", p=p, b=b, lay=lay, active="network")

    @app.get("/p/<int:pid>/wbs")
    def wbs(pid):
        p = project_or_404(pid)
        b = service.project_bundle(pid)
        return render_template("wbs.html", p=p, b=b, active="wbs")

    @app.route("/p/<int:pid>/resources", methods=["GET", "POST"])
    def resources(pid):
        p = project_or_404(pid)
        if request.method == "POST":
            rid = request.form.get("id", type=int)
            if request.form.get("action") == "delete" and rid:
                service.delete_resource(pid, rid)
                flash("자원을 삭제했습니다.", "ok")
            else:
                service.save_resource(pid, request.form, rid)
                flash("자원을 저장했습니다.", "ok")
            return redirect(url_for("resources", pid=pid))
        b = service.project_bundle(pid)
        usage = service.resource_usage(b)
        return render_template("resources.html", p=p, b=b, usage=usage, active="resources")

    @app.get("/p/<int:pid>/usage")
    def usage(pid):
        p = project_or_404(pid)
        unit = request.args.get("unit", "week")
        b = service.project_bundle(pid)
        u = service.resource_usage(b, unit)
        return render_template("usage.html", p=p, b=b, usage=u, unit=unit, active="usage")

    @app.get("/p/<int:pid>/delay")
    def delay(pid):
        p = project_or_404(pid)
        b = service.project_bundle(pid)
        return render_template("delay.html", p=p, b=b, reports=service.list_reports(pid), active="delay")

    # ---------------------------------------------------------- 지연 대책 보고서
    @app.post("/p/<int:pid>/report")
    def report_generate(pid):
        project_or_404(pid)
        b = service.project_bundle(pid)
        notes = request.form.get("notes", "").strip()
        content, source = report.generate(b, notes)
        rid = service.save_report(pid, source, notes, content)
        if source != report.model_name():
            flash("OpenAI API 키가 없거나 호출에 실패하여 규칙 기반 초안으로 작성했습니다. "
                  + (content.get("_error") or ""), "warn")
        else:
            flash(f"{source} 로 지연 대책 보고서를 작성했습니다.", "ok")
        return redirect(url_for("report_view", pid=pid, rid=rid))

    @app.get("/p/<int:pid>/report/<int:rid>")
    def report_view(pid, rid):
        p = project_or_404(pid)
        r = service.get_report(pid, rid)
        if r is None:
            abort(404)
        return render_template("report.html", p=p, r=r, c=r["content"], active="delay")

    @app.get("/p/<int:pid>/report/<int:rid>.docx")
    def report_docx(pid, rid):
        p = project_or_404(pid)
        r = service.get_report(pid, rid)
        if r is None:
            abort(404)
        data = report.build_docx(r["content"], dict(p), r)
        return send_file(io.BytesIO(data), as_attachment=True,
                         download_name=f"{p['name']}_지연대책보고서_{r['created_at'][:10]}.docx",
                         mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document")

    @app.post("/p/<int:pid>/report/<int:rid>/delete")
    def report_delete(pid, rid):
        db.execute("DELETE FROM report WHERE id=? AND project_id=?", (rid, pid))
        flash("보고서를 삭제했습니다.", "ok")
        return redirect(url_for("delay", pid=pid))

    # ---------------------------------------------------------- 내보내기
    @app.get("/p/<int:pid>/export.xlsx")
    def export_xlsx(pid):
        p = project_or_404(pid)
        data = exports.build_xlsx(service.project_bundle(pid), service.resource_usage(service.project_bundle(pid)))
        return send_file(io.BytesIO(data), as_attachment=True, download_name=f"{p['name']}_일정표.xlsx",
                         mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    @app.get("/p/<int:pid>/export.pptx")
    def export_pptx(pid):
        p = project_or_404(pid)
        b = service.project_bundle(pid)
        data = exports.build_pptx(b, service.resource_usage(b))
        return send_file(io.BytesIO(data), as_attachment=True, download_name=f"{p['name']}_일정보고.pptx",
                         mimetype="application/vnd.openxmlformats-officedocument.presentationml.presentation")

    @app.get("/p/<int:pid>/export.json")
    def export_json(pid):
        p = project_or_404(pid)
        data = json.dumps(service.export_json(pid), ensure_ascii=False, indent=1).encode("utf-8")
        return send_file(io.BytesIO(data), as_attachment=True, download_name=f"{p['name']}.json",
                         mimetype="application/json")

    # ---------------------------------------------------------- JSON API (간트 화면)
    @app.get("/api/p/<int:pid>")
    def api_get(pid):
        project_or_404(pid)
        return jsonify(service.bundle_json(service.project_bundle(pid)))

    @app.post("/api/p/<int:pid>/tasks")
    def api_save(pid):
        project_or_404(pid)
        items = (request.get_json(silent=True) or {}).get("tasks", [])
        try:
            service.save_tasks(pid, items)
        except (ScheduleError, ValueError) as e:
            return jsonify({"error": str(e)}), 400
        return jsonify(service.bundle_json(service.project_bundle(pid)))

    @app.post("/api/p/<int:pid>/baseline")
    def api_baseline(pid):
        project_or_404(pid)
        service.set_baseline(pid, clear=(request.get_json(silent=True) or {}).get("clear", False))
        return jsonify(service.bundle_json(service.project_bundle(pid)))

    @app.post("/api/p/<int:pid>/status-date")
    def api_status_date(pid):
        project_or_404(pid)
        v = (request.get_json(silent=True) or {}).get("status_date") or None
        db.execute("UPDATE project SET status_date=? WHERE id=?", (v, pid))
        return jsonify(service.bundle_json(service.project_bundle(pid)))

    @app.errorhandler(404)
    def not_found(_):
        return render_template("message.html", title="페이지를 찾을 수 없습니다",
                               body="요청한 프로젝트나 보고서가 없습니다."), 404

    app.jinja_env.globals["DEP_TYPES"] = DEP_TYPES
    return app


app = create_app()

if __name__ == "__main__":
    app.run(host=os.environ.get("HOST", "127.0.0.1"), port=int(os.environ.get("PORT", 5000)),
            debug=os.environ.get("FLASK_DEBUG") == "1")
