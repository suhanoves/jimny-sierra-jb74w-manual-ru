from __future__ import annotations

import argparse
import os
import posixpath
import queue
import subprocess
import threading
import time
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse


RELOAD_SNIPPET = b"""
<script>
(() => {
  const events = new EventSource("/__reload");
  events.onmessage = event => {
    if (event.data === "reload") location.reload();
  };
})();
</script>
"""


class ReloadState:
    def __init__(self) -> None:
        self.clients: list[queue.Queue[str]] = []
        self.lock = threading.Lock()

    def subscribe(self) -> queue.Queue[str]:
        client: queue.Queue[str] = queue.Queue()
        with self.lock:
            self.clients.append(client)
        return client

    def unsubscribe(self, client: queue.Queue[str]) -> None:
        with self.lock:
            if client in self.clients:
                self.clients.remove(client)

    def reload(self) -> None:
        with self.lock:
            clients = list(self.clients)
        for client in clients:
            client.put("reload")


class Handler(SimpleHTTPRequestHandler):
    site_dir: Path
    reload_state: ReloadState

    def do_GET(self) -> None:
        if self.path == "/__reload":
            self.handle_reload()
            return
        super().do_GET()

    def handle_reload(self) -> None:
        client = self.reload_state.subscribe()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        try:
            self.wfile.write(b": connected\n\n")
            self.wfile.flush()
            while True:
                try:
                    message = client.get(timeout=15)
                    self.wfile.write(f"data: {message}\n\n".encode())
                except queue.Empty:
                    self.wfile.write(b": ping\n\n")
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            self.reload_state.unsubscribe(client)

    def translate_path(self, path: str) -> str:
        path = urlparse(path).path
        path = posixpath.normpath(unquote(path))
        parts = [part for part in path.split("/") if part and part not in (os.curdir, os.pardir)]
        resolved = self.site_dir
        for part in parts:
            resolved /= part
        if resolved.is_dir():
            resolved /= "index.html"
        return str(resolved)

    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def copyfile(self, source, outputfile) -> None:  # type: ignore[no-untyped-def]
        path = Path(source.name)
        if path.suffix.lower() not in {".html", ".htm"}:
            super().copyfile(source, outputfile)
            return
        content = source.read()
        marker = b"</body>"
        if marker in content:
            content = content.replace(marker, RELOAD_SNIPPET + marker, 1)
        outputfile.write(content)


def snapshot(paths: list[Path]) -> dict[Path, int]:
    result: dict[Path, int] = {}
    for path in paths:
        if path.is_dir():
            for file_path in path.rglob("*"):
                if file_path.is_file() and "site" not in file_path.parts:
                    result[file_path] = file_path.stat().st_mtime_ns
        elif path.exists():
            result[path] = path.stat().st_mtime_ns
    return result


def build(config: str) -> bool:
    env = os.environ.copy()
    env["NO_MKDOCS_2_WARNING"] = "1"
    env["DISABLE_MKDOCS_2_WARNING"] = "true"
    command = ["uv", "run", "mkdocs", "build", "-f", config]
    return subprocess.run(command, env=env).returncode == 0


def watch(paths: list[Path], config: str, reload_state: ReloadState, interval: float) -> None:
    previous = snapshot(paths)
    while True:
        time.sleep(interval)
        current = snapshot(paths)
        if current == previous:
            continue
        previous = current
        print("Change detected, rebuilding documentation...", flush=True)
        if build(config):
            reload_state.reload()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="mkdocs.dev.yml")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--interval", type=float, default=1.0)
    args = parser.parse_args()

    root = Path.cwd()
    site_dir = root / "site"
    watched = [root / "docs", root / "mkdocs.yml", root / "mkdocs.dev.yml", root / "pyproject.toml"]

    if not build(args.config):
        raise SystemExit(1)

    reload_state = ReloadState()
    Handler.site_dir = site_dir
    Handler.reload_state = reload_state

    thread = threading.Thread(target=watch, args=(watched, args.config, reload_state, args.interval), daemon=True)
    thread.start()

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"Serving on http://{args.host}:{args.port}/", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
