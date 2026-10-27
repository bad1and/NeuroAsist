from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
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
    files: tuple[dict[str, object], ...] = ()
    delivery: str | None = None
    source_url: str | None = None
    terms_url: str | None = None


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


def catalog_specs() -> tuple[ModelSpec, ...]:
    catalog = json.loads(Path(__file__).with_name("catalog.json").read_text(encoding="utf-8"))
    for item in catalog:
        if item.get("delivery") == "upstream_download":
            repository, revision = item["repository"], item["revision"]
            if not re.fullmatch(r"[\w.-]+/[\w.-]+", repository) or not re.fullmatch(r"[0-9a-f]{40}", revision):
                raise ValueError(f"Invalid pinned upstream model: {item['id']}")
            for file in item["files"]:
                path = file["path"]
                if (not path or "\\" in path or path.startswith("/") or any(part in {"", ".", ".."} for part in path.split("/"))
                        or file["url"] != f"https://huggingface.co/{repository}/resolve/{revision}/{path}"):
                    raise ValueError(f"Model file must use the pinned upstream source: {item['id']}/{path}")
    return tuple(ModelSpec(id=item["id"], name=item["name"], version=item["revision"], url="", relative_path=item["relative_path"],
                           sha256=hashlib.sha256(json.dumps(item["files"], sort_keys=True).encode()).hexdigest(),
                           size_bytes=item["size_bytes"], files=tuple(item["files"]), license=item.get("license"),
                           delivery=item.get("delivery"), source_url=item.get("source_url"), terms_url=item.get("terms_url")) for item in catalog)


DEFAULT_SPECS = (SILERO_VAD, SMART_TURN_V3_2, *catalog_specs())


def require_managed_model(model_id: str, path: Path) -> None:
    """Reject missing or altered weights before a runtime deserializes them."""
    if os.getenv("NEUROASIST_MANAGED_MODELS") != "1":
        return
    from .location import model_root
    root = model_root(Path(os.environ["NEUROASIST_APP_DATA_DIR"]))
    manager = ModelManager(root)
    if path.resolve() != manager.path_for(model_id).resolve() or not manager.model_state(model_id)["installed"]:
        raise RuntimeError("Модель отсутствует или повреждена. Откройте Настройки → Подключения → Локальные модели и повторите загрузку.")


class ModelManager:
    """Downloads pinned model files outside the repository and verifies every byte."""

    def __init__(
        self,
        root: Path,
        publish=None,
        specs: tuple[ModelSpec, ...] = DEFAULT_SPECS,
    ) -> None:
        self.root = root
        self._publish = publish or (lambda *_: None)
        self._specs = {spec.id: spec for spec in specs}
        self._progress: dict[str, dict[str, object]] = {}
        self._lock = threading.Lock()
        self._cancel: dict[str, threading.Event] = {}
        self._workers: dict[str, threading.Thread] = {}
        self._verified: dict[Path, tuple[int, int, str]] = {}

    def specs(self) -> list[ModelSpec]:
        return list(self._specs.values())

    def path_for(self, model_id: str) -> Path:
        return self.root / self._specs[model_id].relative_path

    def model_state(self, model_id: str) -> dict[str, object]:
        spec = self._specs[model_id]
        path = self.path_for(model_id)
        with self._lock:
            progress = dict(self._progress.get(model_id, {}))
        installed = self._installed(spec)
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
            "delivery": spec.delivery,
            "source_url": spec.source_url,
            "terms_url": spec.terms_url,
            "status": progress.get("status", "installed" if installed else "not_installed"),
            "downloaded_bytes": progress.get("downloaded_bytes", spec.size_bytes if installed else 0),
            "total_bytes": progress.get("total_bytes", spec.size_bytes),
            "error": progress.get("error"),
        }

    def states(self) -> list[dict[str, object]]:
        return [self.model_state(model_id) for model_id in self._specs]

    def install_async(self, model_id: str) -> dict[str, object]:
        if model_id not in self._specs:
            raise KeyError(model_id)
        with self._lock:
            already_downloading = (
                self._progress.get(model_id, {}).get("status") in {"downloading", "verifying"}
            )
            if not already_downloading:
                self._progress[model_id] = {
                    "status": "downloading",
                    "downloaded_bytes": 0,
                    "total_bytes": self._specs[model_id].size_bytes,
                    "error": None,
                }
                self._cancel[model_id] = threading.Event()
        # model_state() acquires the same lock to snapshot progress. It must
        # always run after the critical section; the duplicate-install branch
        # previously called it while holding a non-reentrant Lock and hung the
        # request forever.
        if not already_downloading:
            worker = threading.Thread(
                target=self._download,
                args=(model_id,),
                daemon=True,
            )
            self._workers[model_id] = worker
            worker.start()
        return self.model_state(model_id)

    def cancel(self, model_id: str) -> dict[str, object]:
        if model_id not in self._specs:
            raise KeyError(model_id)
        with self._lock:
            if event := self._cancel.get(model_id):
                event.set()
        return self.model_state(model_id)

    def close(self) -> None:
        for event in self._cancel.values():
            event.set()
        for worker in self._workers.values():
            worker.join(timeout=35)

    def _file_matches(self, path: Path, expected: str) -> bool:
        if not path.is_file():
            return False
        stat = path.stat()
        cached = self._verified.get(path)
        if cached and cached[:2] == (stat.st_size, stat.st_mtime_ns):
            return cached[2] == expected
        digest = self._sha256(path)
        self._verified[path] = (stat.st_size, stat.st_mtime_ns, digest)
        return digest == expected

    def _installed(self, spec: ModelSpec) -> bool:
        path = self.path_for(spec.id)
        if spec.files:
            return all(self._file_matches(path / str(item["path"]), str(item["sha256"])) for item in spec.files)
        return self._file_matches(path, spec.sha256)

    def remove(self, model_id: str) -> dict[str, object]:
        if model_id not in self._specs:
            raise KeyError(model_id)
        worker = self._workers.get(model_id)
        if worker is not None and worker.is_alive():
            raise ValueError("Сначала отмените загрузку и дождитесь её остановки.")
        path = self.path_for(model_id)
        if path.is_dir():
            resolved = path.resolve()
            if resolved == self.root.resolve() or not resolved.is_relative_to(self.root.resolve()) or path.is_symlink():
                raise ValueError("Invalid model path")
            shutil.rmtree(path)
        else:
            path.unlink(missing_ok=True)
        staging = self.root / ".downloads" / model_id
        if staging.exists():
            if staging.is_symlink() or staging.is_junction() or not staging.resolve().is_relative_to(self.root.resolve()):
                raise ValueError("Invalid model staging path")
            shutil.rmtree(staging)
        with self._lock:
            self._progress.pop(model_id, None)
        self._publish("models.removed", "info", "Model removed", {"model_id": model_id})
        return self.model_state(model_id)

    def _download(self, model_id: str) -> None:
        spec = self._specs[model_id]
        if spec.files:
            self._download_directory(spec)
            return
        path = self.path_for(model_id)
        temporary = path.with_suffix(".download")
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            if shutil.disk_usage(path.parent).free < spec.size_bytes + 64 * 1024**2:
                raise ValueError("Недостаточно свободного места для модели.")
            digest = hashlib.sha256()
            downloaded = 0
            with urlopen(spec.url, timeout=30) as response, temporary.open("wb") as target:
                total = int(response.headers.get("Content-Length") or spec.size_bytes)
                self._set_progress(model_id, status="downloading", downloaded_bytes=0, total_bytes=total)
                while chunk := response.read(64 * 1024):
                    if self._cancel[model_id].is_set():
                        raise InterruptedError("Загрузка отменена.")
                    if downloaded + len(chunk) > spec.size_bytes:
                        raise ValueError("Размер загрузки превышает ожидаемый объём модели.")
                    target.write(chunk)
                    digest.update(chunk)
                    downloaded += len(chunk)
                    self._set_progress(model_id, status="downloading", downloaded_bytes=downloaded, total_bytes=total)
            if digest.hexdigest().lower() != spec.sha256:
                raise ValueError("checksum mismatch; the downloaded file was discarded")
            if self._cancel[model_id].is_set():
                raise InterruptedError("Загрузка отменена.")
            os.replace(temporary, path)
            self._set_progress(model_id, status="installed", downloaded_bytes=downloaded, total_bytes=downloaded)
            self._publish("models.installed", "info", "Model downloaded and verified", {"model_id": model_id, "version": spec.version})
        except Exception as error:
            temporary.unlink(missing_ok=True)
            self._set_progress(model_id, status="cancelled" if isinstance(error, InterruptedError) else "failed", error=str(error))
            self._publish("models.download_failed", "error", "Model download failed", {"model_id": model_id, "error": str(error)})

    def _download_directory(self, spec: ModelSpec) -> None:
        path = self.path_for(spec.id)
        staging = self.root / ".downloads" / spec.id
        try:
            staging.mkdir(parents=True, exist_ok=True)
            if shutil.disk_usage(staging).free < spec.size_bytes + 64 * 1024**2:
                raise ValueError("Недостаточно свободного места для модели.")
            downloaded = 0
            for item in spec.files:
                if self._cancel[spec.id].is_set():
                    raise InterruptedError("Загрузка отменена.")
                name, expected = str(item["path"]), str(item["sha256"])
                destination = staging / name
                destination.parent.mkdir(parents=True, exist_ok=True)
                legacy = self.root / "huggingface" / "models--TeraSpace--TeraTTSv2" / "snapshots" / spec.version / name
                source = path / name
                if not self._file_matches(destination, expected):
                    candidate = source if self._file_matches(source, expected) else legacy if self._file_matches(legacy, expected) else None
                    if candidate:
                        shutil.copyfile(candidate, destination)
                    else:
                        temporary = destination.with_suffix(destination.suffix + ".download")
                        digest = hashlib.sha256()
                        with urlopen(str(item["url"]), timeout=30) as response, temporary.open("wb") as target:
                            while chunk := response.read(256 * 1024):
                                if self._cancel[spec.id].is_set():
                                    raise InterruptedError("Загрузка отменена.")
                                if target.tell() + len(chunk) > int(item["size_bytes"]):
                                    raise ValueError("Размер загрузки превышает ожидаемый объём модели.")
                                target.write(chunk)
                                digest.update(chunk)
                                self._set_progress(spec.id, downloaded_bytes=downloaded + target.tell())
                        if digest.hexdigest() != expected:
                            temporary.unlink(missing_ok=True)
                            raise ValueError("Контрольная сумма модели не совпадает.")
                        os.replace(temporary, destination)
                downloaded += int(item["size_bytes"])
                self._set_progress(spec.id, downloaded_bytes=downloaded)
            self._set_progress(spec.id, status="verifying")
            if self._cancel[spec.id].is_set():
                raise InterruptedError("Загрузка отменена.")
            for item in spec.files:
                if not self._file_matches(staging / str(item["path"]), str(item["sha256"])):
                    raise ValueError("Контрольная сумма модели не совпадает.")
            path.mkdir(parents=True, exist_ok=True)
            for item in spec.files:
                target = path / str(item["path"])
                target.parent.mkdir(parents=True, exist_ok=True)
                os.replace(staging / str(item["path"]), target)
            self._set_progress(spec.id, status="installed", downloaded_bytes=downloaded, error=None)
            self._publish("models.installed", "info", "Model downloaded and verified", {"model_id": spec.id})
        except Exception as error:
            self._set_progress(spec.id, status="cancelled" if isinstance(error, InterruptedError) else "failed", error=str(error))
            self._publish("models.download_failed", "warning", "Model download did not finish", {"model_id": spec.id})

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
