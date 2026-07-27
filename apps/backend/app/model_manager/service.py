from __future__ import annotations

import hashlib
import os
import threading
from dataclasses import dataclass
from pathlib import Path
from urllib.request import urlopen


@dataclass(frozen=True)
class ModelSpec:
    id: str
    name: str
    version: str
    url: str
    relative_path: str
    sha256: str
    size_bytes: int
    restart_required: bool = True
    license: str | None = None


SILERO_VAD = ModelSpec(
    id="silero-vad",
    name="Silero VAD",
    version="6.2.1",
    url="https://raw.githubusercontent.com/snakers4/silero-vad/7e30209a3e901f9842f81b225f3e93d8199902b1/src/silero_vad/data/silero_vad.jit",
    relative_path="silero-vad/6.2.1/silero_vad.jit",
    sha256="e1122837f4154c511485fe0b9c64455f7b929c96fbb8d79fbdb336383ebd3720",
    size_bytes=2_272_526,
)

SMART_TURN_V3_2 = ModelSpec(
    id="smart-turn-v3.2",
    name="Smart Turn",
    version="3.2",
    url=(
        "https://huggingface.co/pipecat-ai/smart-turn-v3/resolve/"
        "f766f81d3cfdf7737ac64aad813d91bbfd56bf93/smart-turn-v3.2-cpu.onnx?download=true"
    ),
    relative_path="smart-turn/3.2/smart-turn-v3.2-cpu.onnx",
    sha256="2bb026316b14a660486a75b1733cd3fbab8c2fd0314dc9af7be49f8cca967e4f",
    size_bytes=8_679_182,
    license="BSD-2-Clause",
)


class ModelManager:
    """Downloads pinned model files outside the repository and verifies every byte."""

    def __init__(
        self,
        root: Path,
        publish=None,
        specs: tuple[ModelSpec, ...] = (SILERO_VAD, SMART_TURN_V3_2),
    ) -> None:
        self.root = root
        self._publish = publish or (lambda *_: None)
        self._specs = {spec.id: spec for spec in specs}
        self._progress: dict[str, dict[str, object]] = {}
        self._lock = threading.Lock()

    def specs(self) -> list[ModelSpec]:
        return list(self._specs.values())

    def path_for(self, model_id: str) -> Path:
        return self.root / self._specs[model_id].relative_path

    def model_state(self, model_id: str) -> dict[str, object]:
        spec = self._specs[model_id]
        path = self.path_for(model_id)
        with self._lock:
            progress = dict(self._progress.get(model_id, {}))
        installed = path.is_file() and self._sha256(path) == spec.sha256
        return {
            "id": spec.id,
            "name": spec.name,
            "version": spec.version,
            "installed": installed,
            "size_bytes": spec.size_bytes,
            "location": str(path) if path.exists() else None,
            "sha256": spec.sha256,
            "restart_required": spec.restart_required,
            "license": spec.license,
            "status": progress.get("status", "installed" if installed else "not_installed"),
            "downloaded_bytes": progress.get("downloaded_bytes", path.stat().st_size if installed else 0),
            "total_bytes": progress.get("total_bytes", spec.size_bytes),
            "error": progress.get("error"),
        }

    def states(self) -> list[dict[str, object]]:
        return [self.model_state(model_id) for model_id in self._specs]

    def install_async(self, model_id: str) -> dict[str, object]:
        if model_id not in self._specs:
            raise KeyError(model_id)
        with self._lock:
            if self._progress.get(model_id, {}).get("status") == "downloading":
                return self.model_state(model_id)
            self._progress[model_id] = {"status": "downloading", "downloaded_bytes": 0}
        threading.Thread(target=self._download, args=(model_id,), daemon=True).start()
        return self.model_state(model_id)

    def remove(self, model_id: str) -> dict[str, object]:
        if model_id not in self._specs:
            raise KeyError(model_id)
        path = self.path_for(model_id)
        path.unlink(missing_ok=True)
        with self._lock:
            self._progress.pop(model_id, None)
        self._publish("models.removed", "info", "Model removed", {"model_id": model_id})
        return self.model_state(model_id)

    def _download(self, model_id: str) -> None:
        spec = self._specs[model_id]
        path = self.path_for(model_id)
        temporary = path.with_suffix(".download")
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            digest = hashlib.sha256()
            downloaded = 0
            with urlopen(spec.url, timeout=30) as response, temporary.open("wb") as target:
                total = int(response.headers.get("Content-Length") or spec.size_bytes)
                self._set_progress(model_id, status="downloading", downloaded_bytes=0, total_bytes=total)
                while chunk := response.read(64 * 1024):
                    target.write(chunk)
                    digest.update(chunk)
                    downloaded += len(chunk)
                    self._set_progress(model_id, status="downloading", downloaded_bytes=downloaded, total_bytes=total)
            if digest.hexdigest().lower() != spec.sha256:
                raise ValueError("checksum mismatch; the downloaded file was discarded")
            os.replace(temporary, path)
            self._set_progress(model_id, status="installed", downloaded_bytes=downloaded, total_bytes=downloaded)
            self._publish("models.installed", "info", "Model downloaded and verified", {"model_id": model_id, "version": spec.version})
        except Exception as error:
            temporary.unlink(missing_ok=True)
            self._set_progress(model_id, status="failed", error=str(error))
            self._publish("models.download_failed", "error", "Model download failed", {"model_id": model_id, "error": str(error)})

    def _set_progress(self, model_id: str, **values: object) -> None:
        with self._lock:
            self._progress.setdefault(model_id, {}).update(values)

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as source:
            while chunk := source.read(64 * 1024):
                digest.update(chunk)
        return digest.hexdigest()
