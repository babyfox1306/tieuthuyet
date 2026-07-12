#!/usr/bin/env python3
"""Local UI — concept form + pipeline + viết/duyệt chương + export."""

from __future__ import annotations

import json
import sys
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import yaml

from factory.engine.lib.concept_cli import concept_check
from factory.engine.lib.language import normalize_language
from factory.engine.lib.narrative_schema import (
    concept_content_errors,
    concept_validation_errors,
    load_concept,
)
from factory.engine.paths import bible_path, load_config, workspace_dir

from factory.ui import factory_workflow

UI_VERSION = "2026-07-12b"

_workflow_lock = __import__("threading").Lock()
_workflow_cache = None  # type: ignore[var-annotated]


def _workflow(*, force_reload: bool = False):
    """Return factory_workflow module (stable across concurrent requests).

    Do NOT purge ``sys.modules`` on every request — ThreadingHTTPServer runs
    overlapping handlers; a purge mid-request causes KeyError /
    ``NoneType.__dict__`` races (UI: \"Lỗi tải: 'factory.ui.factory_workflow'\").

    After editing engine/UI code: restart the UI server, or POST /api/reload.
    """
    global _workflow_cache

    if force_reload:
        import sys

        with _workflow_lock:
            for name in list(sys.modules):
                if name == "factory.ui.factory_workflow" or name.startswith(
                    "factory.engine.lib."
                ):
                    sys.modules.pop(name, None)
            import factory.ui.factory_workflow as fw  # noqa: F401

            _workflow_cache = fw
            return fw

    if _workflow_cache is not None:
        return _workflow_cache

    with _workflow_lock:
        if _workflow_cache is not None:
            return _workflow_cache
        import factory.ui.factory_workflow as fw

        _workflow_cache = fw
        return fw


def _concept_mark_ready(ws: Path) -> tuple[bool, list[str]]:
    from factory.engine.lib.concept_cli import concept_mark_ready

    return concept_mark_ready(ws)

UI_DIR = Path(__file__).resolve().parent / "static"
WORKSPACES_ROOT = ROOT / "factory" / "workspaces"
DEFAULT_PORT = 8765

SUPPORTED_LANGUAGES = [
    {"code": "vi", "label": "Tiếng Việt", "hint": "Viết toàn bộ nội dung form bằng tiếng Việt"},
    {"code": "en", "label": "English", "hint": "Write all story content in English"},
]


def _load_direction(ws: Path) -> dict:
    path = ws / "direction.yaml"
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _save_direction(ws: Path, data: dict) -> None:
    path = ws / "direction.yaml"
    path.write_text(
        yaml.dump(data, allow_unicode=True, default_flow_style=False, sort_keys=False),
        encoding="utf-8",
    )


def _sync_workspace_language(ws: Path, lang: str) -> None:
    """Đồng bộ target_language — UI concept là nơi chọn chính."""
    from factory.engine.lib.operator_sync import write_language_everywhere

    write_language_everywhere(ws, lang)


def _sync_direction_manifest_from_concept(ws: Path, concept: dict) -> None:
    """Kéo concept → direction + manifest (arc, spice, setting, blurb)."""
    from factory.engine.lib.workspace_metadata import sync_direction_from_concept

    sync_direction_from_concept(ws, preserve_gate_status=True, force_setting=False)


def list_workspaces() -> list[str]:
    if not WORKSPACES_ROOT.exists():
        return []
    return sorted(
        p.name for p in WORKSPACES_ROOT.iterdir() if p.is_dir() and not p.name.startswith(".")
    )


def create_workspace(body: dict) -> dict:
    """POST /api/workspaces — tạo folder workspace mới (blank hoặc copy template)."""
    from factory.engine.lib.workspace_init import (
        init_blank_workspace,
        init_workspace_from_template,
        normalize_workspace_id,
        validate_workspace_id,
    )

    raw_id = (body.get("id") or body.get("workspace_id") or "").strip()
    ws_id = normalize_workspace_id(raw_id)
    err = validate_workspace_id(ws_id)
    if err:
        return {"ok": False, "error": err}

    if ws_id in list_workspaces():
        return {"ok": False, "error": f"workspace '{ws_id}' đã tồn tại"}

    title = (body.get("title") or "").strip()
    lang = normalize_language(body.get("target_language") or body.get("language") or "en")
    mode = (body.get("mode") or "blank").strip().lower()
    template_id = (body.get("template") or body.get("from_workspace") or "ceo-contract").strip()

    try:
        if mode == "template":
            if template_id == ws_id:
                return {"ok": False, "error": "template và id mới phải khác nhau"}
            if template_id not in list_workspaces():
                return {"ok": False, "error": f"template '{template_id}' không tồn tại"}
            path = init_workspace_from_template(
                ws_id,
                template_id=template_id,
                copy_narrative=body.get("copy_narrative", True),
                copy_concept=body.get("copy_concept", True),
            )
        else:
            tc = body.get("total_chapters")
            path = init_blank_workspace(
                ws_id,
                title=title,
                target_language=lang,
                total_chapters=int(tc) if tc is not None else None,
            )
    except FileExistsError as exc:
        return {"ok": False, "error": str(exc)}
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}

    if body.get("total_chapters") is not None:
        from factory.engine.lib.book_config import set_total_chapters

        set_total_chapters(ws_id, 1, int(body["total_chapters"]))

    return {
        "ok": True,
        "workspace": ws_id,
        "path": str(path),
        "mode": mode,
        "message": "Tạo workspace xong — điền Concept rồi chạy Pipeline",
    }


def concept_to_json(ws_id: str) -> dict:
    ws = workspace_dir(ws_id)
    concept = load_concept(ws)
    direction = _load_direction(ws)
    lang = normalize_language(
        concept.get("target_language") or direction.get("target_language") or "vi"
    )

    return {
        "workspace": ws_id,
        "concept": concept,
        "target_language": lang,
        "languages": SUPPORTED_LANGUAGES,
        "direction": {
            "target_language": lang,
            "narrative_profile": direction.get("narrative_profile", ""),
            "narrative_status": direction.get("narrative_status", "draft"),
            "publish_strategy": direction.get("publish_strategy", ""),
        },
        "validation_errors": concept_validation_errors(concept),
        "ready": len(concept_validation_errors(concept)) == 0,
    }


def save_concept(ws_id: str, body: dict, *, mark_ready: bool = False) -> dict:
    ws = workspace_dir(ws_id)
    ws.mkdir(parents=True, exist_ok=True)

    lang = normalize_language(body.get("target_language"))
    _sync_workspace_language(ws, lang)

    data = {
        "concept_status": "ready" if mark_ready else "draft",
        "target_language": lang,
        "title": body.get("title", "") or "",
        "logline": body.get("logline", "") or "",
        "author_directive": body.get("author_directive", "") or "",
        "surface_plot": body.get("surface_plot", "") or "",
        "true_plot": body.get("true_plot", "") or "",
        "must_include": body.get("must_include") or [],
        "must_avoid": body.get("must_avoid") or [],
        "ending_book1": body.get("ending_book1", "") or "",
        "hook_book2": body.get("hook_book2", "") or "",
        "notes": body.get("notes", "") or "",
    }

    if not mark_ready:
        path = ws / "concept.yaml"
        path.write_text(
            yaml.dump(data, allow_unicode=True, default_flow_style=False, sort_keys=False),
            encoding="utf-8",
        )
        _sync_direction_manifest_from_concept(ws, data)
        from factory.engine.lib.operator_sync import write_title_everywhere

        write_title_everywhere(ws, data.get("title", ""))
        return concept_to_json(ws_id)

    # save draft first then validate for ready
    path = ws / "concept.yaml"
    data["concept_status"] = "draft"
    path.write_text(
        yaml.dump(data, allow_unicode=True, default_flow_style=False, sort_keys=False),
        encoding="utf-8",
    )
    ok, errs = _concept_mark_ready(ws)
    if not ok:
        return {"ok": False, "errors": errs, **concept_to_json(ws_id)}
    concept = load_concept(ws)
    _sync_direction_manifest_from_concept(ws, concept)
    from factory.engine.lib.operator_sync import write_title_everywhere

    write_title_everywhere(ws, concept.get("title", ""))
    return {"ok": True, **concept_to_json(ws_id)}


def run_develop(ws_id: str, pass_name: str = "all") -> dict:
    from factory.engine.lib.narrative_developer import develop_narrative

    try:
        paths = develop_narrative(ws_id, pass_name=pass_name)
        return {
            "ok": True,
            "files": [str(p) for p in paths],
            **concept_to_json(ws_id),
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc), **concept_to_json(ws_id)}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args) -> None:
        print(f"[ui] {self.address_string()} {fmt % args}")

    def _json(self, code: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        try:
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError):
            # Client đóng tab / timeout trước khi nhận xong — bỏ qua
            pass

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b"{}"
        return json.loads(raw.decode("utf-8"))

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path

        if path in ("/", "/dashboard.html"):
            html = (UI_DIR / "dashboard.html").read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(html)))
            self.end_headers()
            self.wfile.write(html)
            return

        if path == "/index.html":
            html = (UI_DIR / "index.html").read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(html)))
            self.end_headers()
            self.wfile.write(html)
            return

        if path == "/api/workspaces":
            cfg = load_config()
            self._json(
                200,
                {
                    "workspaces": list_workspaces(),
                    "languages": SUPPORTED_LANGUAGES,
                    "default_workspace": cfg.get("default_workspace", ""),
                },
            )
            return

        if path.startswith("/api/concept/"):
            ws_id = path.split("/api/concept/", 1)[1].strip("/")
            if not ws_id or "/" in ws_id:
                self._json(400, {"error": "invalid workspace"})
                return
            try:
                self._json(200, concept_to_json(ws_id))
            except Exception as exc:
                self._json(500, {"error": str(exc)})
            return

        if path.startswith("/api/pipeline/") and path.endswith("/batch/reset"):
            rest = path[len("/api/pipeline/") : -len("/batch/reset")].strip("/")
            ws_id = rest.split("/")[0] if rest else ""
            if not ws_id:
                self._json(400, {"error": "invalid workspace"})
                return
            try:
                self._json(200, _workflow().reset_batch_lock(ws_id))
            except Exception as exc:
                self._json(500, {"error": str(exc)})
            return

        if path.startswith("/api/pipeline/") and path.endswith("/batch"):
            rest = path[len("/api/pipeline/") : -len("/batch")].strip("/")
            ws_id = rest.split("/")[0] if rest else ""
            if not ws_id:
                self._json(400, {"error": "invalid workspace"})
                return
            try:
                self._json(200, _workflow().get_batch_progress(ws_id))
            except Exception as exc:
                self._json(500, {"error": str(exc)})
            return

        if path.startswith("/api/pipeline/"):
            rest = path[len("/api/pipeline/") :].strip("/")
            parts = rest.split("/")
            ws_id = parts[0] if parts else ""
            if not ws_id:
                self._json(400, {"error": "invalid workspace"})
                return
            qs = parse_qs(parsed.query)
            book = int(qs.get("book", ["1"])[0])
            try:
                self._json(200, _workflow().pipeline_status(ws_id, book))
            except Exception as exc:
                self._json(500, {"error": str(exc)})
            return

        if path.startswith("/api/chapters/"):
            rest = path[len("/api/chapters/") :].strip("/")
            parts = rest.split("/")
            ws_id = parts[0] if parts else ""
            if not ws_id:
                self._json(400, {"error": "invalid workspace"})
                return
            qs = parse_qs(parsed.query)
            book = int(qs.get("book", ["1"])[0])
            try:
                if len(parts) == 1:
                    self._json(200, {"chapters": _workflow().chapter_list(ws_id, book)})
                elif len(parts) == 2 and parts[1].isdigit():
                    ch = int(parts[1])
                    self._json(200, _workflow().chapter_get(ws_id, ch, book))
                else:
                    self._json(400, {"error": "invalid chapter path"})
            except Exception as exc:
                self._json(500, {"error": str(exc)})
            return

        self.send_error(404)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        body = self._read_json()

        if path == "/api/reload":
            try:
                fw = _workflow(force_reload=True)
                self._json(
                    200,
                    {
                        "ok": True,
                        "reloaded": True,
                        "module": getattr(fw, "__file__", None),
                        "ui_version": UI_VERSION,
                    },
                )
            except Exception as exc:
                self._json(500, {"ok": False, "error": str(exc)})
            return

        if path == "/api/workspaces":
            try:
                self._json(200, create_workspace(body or {}))
            except Exception as exc:
                self._json(500, {"error": str(exc)})
            return

        if path.startswith("/api/concept/") and path.endswith("/ready"):
            ws_id = path[len("/api/concept/") : -len("/ready")].strip("/")
            try:
                result = save_concept(ws_id, body, mark_ready=True)
                code = 200 if result.get("ok", result.get("ready")) else 400
                self._json(code, result)
            except Exception as exc:
                self._json(500, {"error": str(exc)})
            return

        if path.startswith("/api/concept/") and path.endswith("/develop"):
            ws_id = path[len("/api/concept/") : -len("/develop")].strip("/")
            pass_name = body.get("pass", "all")
            try:
                # Luu form moi nhat + tu danh dau ready neu du dieu kien
                if body.get("author_directive") or body.get("title"):
                    save_concept(ws_id, body, mark_ready=False)
                    ok, errs = _concept_mark_ready(workspace_dir(ws_id))
                    if not ok:
                        self._json(
                            400,
                            {
                                "ok": False,
                                "error": "concept chua du dieu kien de sinh narrative",
                                "errors": errs,
                                **concept_to_json(ws_id),
                            },
                        )
                        return
                result = run_develop(ws_id, pass_name=pass_name)
                code = 200 if result.get("ok") else 400
                self._json(code, result)
            except Exception as exc:
                self._json(500, {"error": str(exc)})
            return

        if path.startswith("/api/concept/") and path.endswith("/check"):
            ws_id = path[len("/api/concept/") : -len("/check")].strip("/")
            errs = concept_check(workspace_dir(ws_id))
            self._json(200, {"errors": errs, "ready": len(errs) == 0})
            return

        if path.startswith("/api/pipeline/") and path.endswith("/batch/reset"):
            ws_id = path[len("/api/pipeline/") : -len("/batch/reset")].strip("/")
            if not ws_id or "/" in ws_id:
                self._json(400, {"error": "invalid workspace"})
                return
            try:
                result = _workflow().reset_batch_lock(ws_id)
                code = 200 if result.get("ok", True) else 400
                self._json(code, result)
            except Exception as exc:
                self._json(500, {"error": str(exc)})
            return

        if path.startswith("/api/pipeline/") and path.endswith("/batch"):
            ws_id = path[len("/api/pipeline/") : -len("/batch")].strip("/")
            mode = body.get("mode", "prep")
            book = int(body.get("book", 1))
            from_ch = int(body.get("from_ch", 1))
            to_ch = body.get("to_ch")
            to_ch = int(to_ch) if to_ch is not None else None
            stop_on_review = bool(body.get("stop_on_review", False))
            auto_from = bool(body.get("auto_from", False))
            write_mode = str(body.get("write_mode") or "supervised").strip().lower()
            if write_mode not in ("supervised", "auto"):
                write_mode = "supervised"
            try:
                wf = _workflow()
                if mode == "prep":
                    result = wf.start_batch_prep(ws_id, book)
                elif mode == "write":
                    result = wf.start_batch_write(
                        ws_id,
                        book,
                        from_ch,
                        to_ch,
                        stop_on_review=stop_on_review,
                        auto_from=auto_from,
                        write_mode=write_mode,
                    )
                elif mode == "full":
                    result = wf.start_batch_full(
                        ws_id,
                        book,
                        from_ch,
                        to_ch,
                        stop_on_review=stop_on_review,
                        auto_from=auto_from,
                        write_mode=write_mode,
                    )
                else:
                    self._json(400, {"error": f"unknown mode: {mode}"})
                    return
                code = 200 if result.get("ok", True) else 400
                self._json(code, result)
            except Exception as exc:
                self._json(500, {"error": str(exc)})
            return

        if path.startswith("/api/pipeline/") and path.endswith("/book-config"):
            ws_id = path[len("/api/pipeline/") : -len("/book-config")].strip("/")
            if not ws_id or "/" in ws_id:
                self._json(400, {"error": "invalid workspace"})
                return
            book = int(body.get("book", 1))
            total = body.get("total_chapters")
            if total is None:
                self._json(400, {"error": "thiếu total_chapters"})
                return
            try:
                result = _workflow().update_book_config(ws_id, book, total_chapters=int(total))
                self._json(200, result)
            except Exception as exc:
                self._json(500, {"error": str(exc)})
            return

        if path.startswith("/api/pipeline/") and path.endswith("/step"):
            ws_id = path[len("/api/pipeline/") : -len("/step")].strip("/")
            action = body.get("action", "")
            book = int(body.get("book", 1))
            try:
                result = _workflow().run_pipeline_step(ws_id, action, book)
                code = 200 if result.get("ok", True) else 400
                self._json(code, result)
            except Exception as exc:
                self._json(500, {"error": str(exc)})
            return

        m_ch = path.startswith("/api/chapters/")
        if m_ch:
            rest = path[len("/api/chapters/") :].strip("/")
            parts = rest.split("/")
            if len(parts) >= 3 and parts[1].isdigit():
                ws_id, ch_s, action = parts[0], parts[1], parts[2]
                ch = int(ch_s)
                book = int(body.get("book", 1))
                try:
                    if action == "write":
                        result = _workflow().chapter_write(ws_id, ch, book)
                    elif action == "approve":
                        result = _workflow().chapter_approve(ws_id, ch, book)
                    elif action == "discard":
                        result = _workflow().chapter_discard(ws_id, ch, book)
                    else:
                        self._json(400, {"error": f"unknown action: {action}"})
                        return
                    code = 200 if result.get("ok", True) else 400
                    self._json(code, result)
                except Exception as exc:
                    self._json(500, {"error": str(exc)})
                return

        if path.startswith("/api/export/") and path.endswith("/qc-epub"):
            ws_id = path[len("/api/export/") : -len("/qc-epub")].strip("/")
            if not ws_id or "/" in ws_id:
                self._json(400, {"error": "invalid workspace"})
                return
            try:
                result = _workflow().run_qc_epub(
                    ws_id, body.get("book_slug"), book=body.get("book")
                )
                code = 200 if result.get("ok") else 400
                self._json(code, result)
            except Exception as exc:
                self._json(500, {"error": str(exc)})
            return

        if path.startswith("/api/export/") and path.endswith("/export-gate"):
            ws_id = path[len("/api/export/") : -len("/export-gate")].strip("/")
            if not ws_id or "/" in ws_id:
                self._json(400, {"error": "invalid workspace"})
                return
            try:
                result = _workflow().run_export_gate(
                    ws_id, body.get("book_slug"), book=body.get("book")
                )
                code = 200 if result.get("ok") else 400
                self._json(code, result)
            except Exception as exc:
                self._json(500, {"error": str(exc)})
            return

        if path.startswith("/api/export/") and path.endswith("/repair-catalog"):
            ws_id = path[len("/api/export/") : -len("/repair-catalog")].strip("/")
            if not ws_id or "/" in ws_id:
                self._json(400, {"error": "invalid workspace"})
                return
            try:
                result = _workflow().run_repair_catalog(
                    ws_id, body.get("book_slug"), book=body.get("book")
                )
                self._json(200, result)
            except Exception as exc:
                self._json(500, {"error": str(exc)})
            return

        if path.startswith("/api/export/"):
            ws_id = path[len("/api/export/") :].strip("/")
            target = body.get("target", "epub")
            try:
                result = _workflow().run_export(
                    ws_id, target, body.get("book_slug"), book=body.get("book")
                )
                code = 200 if result.get("ok") else 400
                self._json(code, result)
            except Exception as exc:
                self._json(500, {"error": str(exc)})
            return

        self.send_error(404)

    def do_PUT(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/concept/"):
            ws_id = parsed.path.split("/api/concept/", 1)[1].strip("/")
            if not ws_id or "/" in ws_id:
                self._json(400, {"error": "invalid workspace"})
                return
            try:
                result = save_concept(ws_id, self._read_json(), mark_ready=False)
                self._json(200, result)
            except Exception as exc:
                self._json(500, {"error": str(exc)})
            return
        self.send_error(404)


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Story Factory UI")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()

    if not UI_DIR.exists():
        print(f"Missing UI static dir: {UI_DIR}")
        sys.exit(1)

    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    url = f"http://127.0.0.1:{args.port}/"
    print(f"[factory-ui] {url} (v{UI_VERSION})")
    print("[factory-ui] Neu vua sua code: Ctrl+C roi chay lai script nay")
    print("[factory-ui] Tab Concept -> Pipeline -> Viet tung chuong -> Xuat sach")
    if not args.no_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[concept-ui] stopped")


if __name__ == "__main__":
    main()
