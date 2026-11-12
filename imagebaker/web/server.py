"""
Standalone HTTP server for ImageBaker Web.

Uses Python's built-in ThreadingHTTPServer so ImageBaker Web works out of the box
on Windows, Linux, and macOS without requiring additional web framework dependencies.
"""

from __future__ import annotations

import json
import mimetypes
import os
import shutil
import socket
import subprocess
import sys
import threading
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from imagebaker import logger
from imagebaker.web.engine import WebAppEngine

STATIC_DIR = Path(__file__).resolve().parent / "static"


class ImageBakerRequestHandler(BaseHTTPRequestHandler):
    engine: WebAppEngine = None  # Set on handler class creation

    def log_message(self, format: str, *args):
        # Keep console clean; log errors via loguru
        pass

    def _send_json(self, payload: dict, status: int = HTTPStatus.OK):
        msg = payload.get("message")
        if msg and getattr(self, "command", "") == "POST":
            if payload.get("ok", True):
                logger.info(f"[{self.path}] {msg}")
            else:
                logger.warning(f"[{self.path}] {msg}")
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_bytes(
        self,
        data: bytes,
        content_type: str,
        status: int = HTTPStatus.OK,
        cache_control: str = "no-cache",
    ):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", cache_control)
        self.end_headers()
        self.wfile.write(data)

    def _read_json_body(self) -> dict:
        content_length = int(self.headers.get("Content-Length", "0"))
        if content_length <= 0:
            return {}
        raw = self.rfile.read(content_length)
        return json.loads(raw.decode("utf-8"))

    def do_GET(self):
        parsed = urlparse(self.path)
        route = parsed.path
        query = parse_qs(parsed.query)

        try:
            if getattr(self.engine, "is_debug", False):
                logger.debug(f"[HTTP GET] {self.path}")

            if route in {"/", "/index.html"}:
                index_file = STATIC_DIR / "index.html"
                self._send_bytes(
                    index_file.read_bytes(),
                    "text/html; charset=utf-8",
                )
                return

            if route == "/favicon.ico":
                target = (STATIC_DIR / "favicon.ico").resolve()
                if target.is_file():
                    self._send_bytes(target.read_bytes(), "image/x-icon")
                    return

            if route == "/logo.png":
                target = (STATIC_DIR / "logo.png").resolve()
                if target.is_file():
                    self._send_bytes(target.read_bytes(), "image/png")
                    return

            if route.startswith("/static/"):
                rel = route[len("/static/") :]
                target = (STATIC_DIR / rel).resolve()
                if not str(target).startswith(str(STATIC_DIR)) or not target.is_file():
                    self._send_json({"ok": False, "message": "Not found"}, HTTPStatus.NOT_FOUND)
                    return
                mime, _ = mimetypes.guess_type(str(target))
                self._send_bytes(target.read_bytes(), mime or "application/octet-stream")
                return

            if route == "/api/state":
                self._send_json({"ok": True, "state": self.engine.get_state_dict()})
                return

            if route == "/api/layerify/image":
                idx = int(query.get("index", ["0"])[0])
                res = self.engine.get_layerify_image_bytes(idx)
                if res is None:
                    self._send_json({"ok": False, "message": "Image not found"}, HTTPStatus.NOT_FOUND)
                    return
                data, mime = res
                self._send_bytes(data, mime, cache_control="public, max-age=60")
                return

            if route == "/api/baker/layer-image":
                cid = int(query.get("canvas_id", ["-1"])[0])
                lid = int(query.get("layer_id", ["-1"])[0])
                step = int(query.get("step", ["0"])[0])
                png_bytes = self.engine.get_baker_layer_png_bytes(cid, lid, step)
                if png_bytes is None:
                    self._send_json({"ok": False, "message": "Layer image not found"}, HTTPStatus.NOT_FOUND)
                    return
                self._send_bytes(png_bytes, "image/png", cache_control="public, max-age=300")
                return

            if route == "/api/baker/exported-file":
                name = Path(query.get("name", [""])[0]).name
                export_dir = self.engine.canvas_config.export_folder.resolve()
                target = (export_dir / name).resolve()
                if not name or target.parent != export_dir or not target.is_file():
                    self._send_json({"ok": False, "message": "File not found"}, HTTPStatus.NOT_FOUND)
                    return
                mime, _ = mimetypes.guess_type(str(target))
                self.send_response(HTTPStatus.OK)
                data = target.read_bytes()
                self.send_header("Content-Type", mime or "application/octet-stream")
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Content-Disposition", f'attachment; filename="{name}"')
                self.end_headers()
                self.wfile.write(data)
                return

            if route == "/api/layerify/browse-folders":
                path_arg = query.get("path", [None])[0]
                info = self.engine.browse_directory(path_arg)
                self._send_json({"ok": True, **info})
                return

            self._send_json({"ok": False, "message": f"Unknown route: {route}"}, HTTPStatus.NOT_FOUND)

        except Exception as err:
            logger.exception(f"GET {route} error: {err}")
            self._send_json(
                {"ok": False, "message": str(err)}, HTTPStatus.INTERNAL_SERVER_ERROR
            )

    def do_POST(self):
        parsed = urlparse(self.path)
        route = parsed.path

        try:
            if getattr(self.engine, "is_debug", False):
                logger.debug(f"[HTTP POST] {self.path}")
            payload = self._read_json_body()
            engine = self.engine

            if route == "/api/settings":
                with engine.lock:
                    if "theme_mode" in payload:
                        engine.theme_mode = (
                            "dark" if payload["theme_mode"] == "dark" else "light"
                        )
                        engine.last_message = f"Theme set to {engine.theme_mode}"
                    if "show_gridlines" in payload:
                        checked = bool(payload["show_gridlines"])
                        engine.layer_config.show_gridlines = checked
                        engine.canvas_config.show_gridlines = checked
                        engine.last_message = (
                            f"Gridlines {'enabled' if checked else 'disabled'}."
                        )
                    if "active_tab" in payload:
                        engine.active_tab = str(payload["active_tab"])
                        if engine.active_tab == "Baker":
                            engine.reload_plugins()
                        engine.last_message = f"Switched to {engine.active_tab} tab"
                    if "viewport" in payload and engine.current_canvas is not None:
                        vp = payload["viewport"]
                        engine.current_canvas.viewport_width = max(
                            200, int(vp.get("width", 960))
                        )
                        engine.current_canvas.viewport_height = max(
                            200, int(vp.get("height", 640))
                        )
                self._send_json({"ok": True, "state": engine.get_state_dict()})
                return

            if route == "/api/layerify/select-image":
                idx = int(payload.get("index", 0))
                with engine.lock:
                    engine._select_image_by_index(idx, save_previous=True)
                self._send_json({"ok": True, "state": engine.get_state_dict()})
                return

            if route == "/api/layerify/remove-image":
                idx = int(payload.get("index", -1))
                ok, msg = engine.remove_image(idx)
                self._send_json({"ok": ok, "message": msg, "state": engine.get_state_dict()})
                return

            if route == "/api/layerify/select-folder":
                ok, msg = engine.select_folder(payload.get("folder_path", "."))
                self._send_json({"ok": ok, "message": msg, "state": engine.get_state_dict()})
                return

            if route == "/api/layerify/upload-images":
                ok, msg = engine.upload_images(
                    payload.get("files") or [],
                    folder_name=payload.get("folder_name"),
                )
                self._send_json({"ok": ok, "message": msg, "state": engine.get_state_dict()})
                return

            if route == "/api/layerify/annotations/update":
                engine.update_annotations(
                    annotations_payload=payload.get("annotations") or [],
                    push_undo=bool(payload.get("push_undo", True)),
                    message=payload.get("message"),
                )
                self._send_json({"ok": True, "state": engine.get_state_dict()})
                return

            if route == "/api/layerify/annotations/action":
                action = payload.get("action")
                if action == "undo":
                    ok, msg = engine.undo_annotation()
                elif action == "redo":
                    ok, msg = engine.redo_annotation()
                elif action == "copy":
                    ok, msg = engine.copy_annotations(payload.get("annotation_ids"))
                elif action == "paste":
                    ok, msg = engine.paste_annotations()
                elif action == "delete":
                    ok, msg = engine.delete_annotations(payload.get("annotation_ids"))
                elif action == "clear":
                    ok, msg = engine.clear_all_annotations_and_layers()
                else:
                    ok, msg = False, f"Unknown annotation action: {action}"
                self._send_json({"ok": ok, "message": msg, "state": engine.get_state_dict()})
                return

            if route == "/api/layerify/annotations/save":
                res = engine.export_annotations_json(
                    all_layers=bool(payload.get("all_layers", True)),
                    file_path=payload.get("file_path"),
                    fmt=str(payload.get("format") or payload.get("fmt") or "default"),
                )
                res["state"] = engine.get_state_dict()
                self._send_json(res)
                return

            if route == "/api/layerify/annotations/load":
                raw_content = payload.get("json_content") or payload.get("content")
                if payload.get("content_b64"):
                    import base64

                    raw_content = base64.b64decode(payload["content_b64"])
                ok, msg = engine.import_annotations_json(
                    all_layers=bool(payload.get("all_layers", True)),
                    file_path=payload.get("file_path"),
                    json_content=raw_content,
                    fmt=str(payload.get("format") or payload.get("fmt") or "auto"),
                    class_names=payload.get("class_names"),
                )
                self._send_json({"ok": ok, "message": msg, "state": engine.get_state_dict()})
                return

            if route == "/api/layerify/labels":
                ok, msg = engine.manage_labels(payload)
                self._send_json({"ok": ok, "message": msg, "state": engine.get_state_dict()})
                return

            if route in ("/api/layerify/model", "/api/predict"):
                action = payload.get(
                    "action", "predict" if route == "/api/predict" else "select"
                )
                if action == "select":
                    with engine.lock:
                        model_name = str(payload.get("model_name", "None"))
                        engine.current_model_name = model_name
                        engine.last_message = f"Model changed to {model_name}"
                    self._send_json(
                        {"ok": True, "message": engine.last_message, "state": engine.get_state_dict()}
                    )
                elif action == "predict":
                    prompt_val = payload.get("text_prompt")
                    if prompt_val is None:
                        prompt_val = payload.get("prompt")
                    ok, msg = engine.run_prediction(text_prompt=prompt_val)
                    self._send_json({"ok": ok, "message": msg, "state": engine.get_state_dict()})
                else:
                    self._send_json({"ok": False, "message": f"Unknown model action: {action}"})
                return

            if route == "/api/layerify/layerify":
                ann_ids = payload.get("annotation_ids")
                is_all = payload.get("all")
                if is_all is None:
                    is_all = ann_ids is None or len(ann_ids) == 0
                ok, msg = engine.layerify_annotations(
                    annotation_ids=ann_ids,
                    layerify_all=bool(is_all),
                )
                self._send_json({"ok": ok, "message": msg, "state": engine.get_state_dict()})
                return

            if route == "/api/baker/canvas":
                ok, msg = engine.manage_canvas(payload)
                self._send_json({"ok": ok, "message": msg, "state": engine.get_state_dict()})
                return

            if route == "/api/baker/layers/add-blank":
                ok, msg = engine.add_blank_layer(
                    width=payload.get("width"),
                    height=payload.get("height"),
                    label=payload.get("label"),
                )
                self._send_json({"ok": ok, "message": msg, "state": engine.get_state_dict()})
                return

            if route == "/api/baker/layers/update":
                ok, msg = engine.update_baker_layers(
                    layers_payload=payload.get("layers") or [],
                    push_undo=bool(payload.get("push_undo", False)),
                    message=payload.get("message"),
                )
                self._send_json({"ok": ok, "message": msg, "state": engine.get_state_dict()})
                return

            if route == "/api/baker/layers/reorder":
                ok, msg = engine.reorder_baker_layers(payload)
                self._send_json({"ok": ok, "message": msg, "state": engine.get_state_dict()})
                return

            if route == "/api/baker/layers/action":
                ok, msg = engine.baker_layer_action(payload)
                self._send_json({"ok": ok, "message": msg, "state": engine.get_state_dict()})
                return

            if route == "/api/baker/plugins":
                ok, msg = engine.manage_plugins(payload)
                self._send_json({"ok": ok, "message": msg, "state": engine.get_state_dict()})
                return

            if route == "/api/baker/states":
                ok, msg = engine.manage_states(payload)
                self._send_json({"ok": ok, "message": msg, "state": engine.get_state_dict()})
                return

            if route == "/api/baker/export":
                res = engine.bake_and_export(
                    mode=payload.get("mode", "current_local"),
                    annotation_format=str(
                        payload.get("annotation_format")
                        or payload.get("format")
                        or "default"
                    ),
                )
                res["state"] = engine.get_state_dict()
                self._send_json(res)
                return

            self._send_json({"ok": False, "message": f"Unknown route: {route}"}, HTTPStatus.NOT_FOUND)

        except Exception as err:
            logger.exception(f"POST {route} error: {err}")
            self._send_json(
                {"ok": False, "message": str(err)}, HTTPStatus.INTERNAL_SERVER_ERROR
            )


def _find_available_port(host: str, preferred_port: int) -> int:
    if preferred_port == 0:
        return 0
    for offset in range(50):
        candidate = preferred_port + offset
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind((host, candidate))
                return candidate
            except OSError:
                continue
    return preferred_port


def create_http_server(
    engine: WebAppEngine,
    host: str = "127.0.0.1",
    port: int = 8000,
) -> tuple[ThreadingHTTPServer, int]:
    bound_port = _find_available_port(host, port)

    class BoundHandler(ImageBakerRequestHandler):
        pass

    BoundHandler.engine = engine
    server = ThreadingHTTPServer((host, bound_port), BoundHandler)
    actual_port = int(server.server_address[1])
    return server, actual_port


def _open_browser_quietly(url: str):
    """Open the default browser while suppressing noisy browser stderr (e.g. Chromium VAAPI/puffin)."""
    try:
        if sys.platform.startswith("linux") and shutil.which("xdg-open"):
            subprocess.Popen(
                ["xdg-open", url],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            return
        if sys.platform == "darwin" and shutil.which("open"):
            subprocess.Popen(
                ["open", url],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            return
    except Exception:
        pass
    try:
        with open(os.devnull, "w") as devnull:
            old_out = os.dup(1)
            old_err = os.dup(2)
            try:
                os.dup2(devnull.fileno(), 1)
                os.dup2(devnull.fileno(), 2)
                webbrowser.open(url)
            finally:
                os.dup2(old_out, 1)
                os.dup2(old_err, 2)
                os.close(old_out)
                os.close(old_err)
    except Exception:
        pass


def run_web_server(
    models_file: str = "loaded_models.py",
    project_dir: str = ".",
    configs_file: str = "imagebaker/core/configs.py",
    host: str = "127.0.0.1",
    port: int = 8000,
    open_browser: bool = True,
    debug: bool = False,
):
    """Initialize WebAppEngine and start the standalone ImageBaker Web server."""
    if debug:
        import logging

        logging.basicConfig(level=logging.DEBUG)
        try:
            logger.remove()
            logger.add(sys.stderr, level="DEBUG")
        except Exception:
            pass

    engine = WebAppEngine(
        models_file=models_file,
        project_dir=project_dir,
        configs_file=configs_file,
        is_debug=debug,
    )
    server, bound_port = create_http_server(engine, host=host, port=port)
    url = f"http://{host}:{bound_port}"
    mode_str = " (DEBUG MODE)" if debug else ""
    logger.info(f"ImageBaker Web{mode_str} running at {url}")
    print(f"\n  ImageBaker Web v{engine.get_state_dict()['version']}{mode_str} is running at: {url}")
    if debug:
        print("  [DEBUG MODE] Debug server active with verbose logging and debug state dumps.")
    print("  Press Ctrl+C to stop the server.\n")

    if open_browser:
        threading.Timer(0.4, lambda: _open_browser_quietly(url)).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("Shutting down ImageBaker Web server...")
    finally:
        server.server_close()
        if engine.layer_config.cleanup_on_exit:
            if engine.layer_config.bake_dir.exists():
                shutil.rmtree(engine.layer_config.bake_dir, ignore_errors=True)
            if engine.layer_config.cache_dir.exists():
                shutil.rmtree(engine.layer_config.cache_dir, ignore_errors=True)
        else:
            engine.save_current_image_annotations(delete_if_empty=False)
