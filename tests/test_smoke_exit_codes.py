"""Exercise both real PowerShell smoke scripts against disposable local cores."""
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys

import pytest

SHELL = shutil.which("pwsh") or shutil.which("powershell")
ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.skipif(os.name != "nt" or not SHELL, reason="Windows PowerShell integration")
@pytest.mark.parametrize("script,parameter", [("smoke_desktop_core.ps1", "-Python"), ("smoke_packaged_runtime.ps1", "-Executable")])
@pytest.mark.parametrize("exit_code", [0, 7])
def test_smoke_requires_zero_exit_after_authorized_shutdown(tmp_path, script, parameter, exit_code):
    # sitecustomize runs before -m or interactive startup, so the child is an
    # isolated fake HTTP core, never the real backend or a user profile.
    (tmp_path / "sitecustomize.py").write_text('''
import os
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread
class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args): pass
    def do_GET(self):
        authorized = self.headers.get("X-NeuroAsist-Token") == os.environ["NEUROASIST_DESKTOP_TOKEN"]
        self.send_response(200 if authorized else 401)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"status":"ok"}')
    def do_POST(self):
        if self.headers.get("X-NeuroAsist-Token") != os.environ["NEUROASIST_DESKTOP_TOKEN"]:
            self.send_response(401); self.end_headers(); return
        self.send_response(200); self.send_header("Content-Type", "application/json"); self.end_headers()
        self.wfile.write(b'{"status":"stopping"}'); self.wfile.flush()
        Thread(target=self.server.shutdown, daemon=True).start()
server = HTTPServer(("127.0.0.1", int(os.environ["NEUROASIST_PORT"])), Handler)
server.serve_forever(poll_interval=0.01)
server.server_close()
os._exit(int(os.environ["IRIS_TEST_EXIT_CODE"]))
''', encoding="utf-8")
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    environment = {**os.environ, "PYTHONPATH": str(tmp_path), "IRIS_TEST_EXIT_CODE": str(exit_code)}
    result = subprocess.run([SHELL, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File",
        str(ROOT / "scripts" / script), parameter, sys.executable, "-Port", str(port)],
        cwd=ROOT, env=environment, capture_output=True, text=True, timeout=55)
    output = result.stdout + result.stderr
    assert (result.returncode == 0) is (exit_code == 0), output
    if exit_code:
        assert f"code {exit_code}" in output, output
