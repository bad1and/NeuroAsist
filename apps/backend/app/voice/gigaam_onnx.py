"""Pinned FP32 GigaAM RNNT with CUDA preference and explicit CPU recovery."""

import asyncio
import gc
import logging
import os
import threading
import time
from pathlib import Path

from apps.backend.app.voice.audio import Pcm16Audio, decode_audio_file
from apps.backend.app.voice.providers import GigaAMSTTProvider, STTProvider, STTResult

logger = logging.getLogger(__name__)
MODEL_REVISION = "322c3b29492673eb7d0b434bfa9dfb8653e34d02"
MODEL_FILES = (
    "config.json", "v3_vocab.txt", "v3_rnnt.yaml",
    "v3_rnnt_encoder.onnx", "v3_rnnt_decoder.onnx", "v3_rnnt_joint.onnx",
)


class GigaAMOnnxSTTProvider(STTProvider):
    def __init__(self, model_name: str, device: str, model_dir: Path, *,
                 threads: int = 4, cpu_threads: int = 8) -> None:
        if model_name not in {"v3_rnnt", "gigaam-v3-rnnt"}:
            raise ValueError("GigaAM ONNX supports the validated v3_rnnt FP32 model")
        if device not in {"auto", "cuda", "cpu"}:
            raise ValueError("VOICE_STT_DEVICE must be one of: cpu, cuda, auto")
        if min(threads, cpu_threads) < 1:
            raise ValueError("ONNX thread counts must be positive")
        self._device = device
        self._model_dir = model_dir
        self._threads = threads
        self._cpu_threads = cpu_threads
        self._model = None
        self._selected_device = None
        # Model loading, warmup and inference share one lock. A CPU retry cannot
        # race another utterance or leave an old CUDA session serving requests.
        self._lock = threading.Lock()
        self._chunker = GigaAMSTTProvider("v3_rnnt", "cpu")
        self._warmed_up = False
        self._warmup_duration_ms = None
        self._fallback_reason = None
        self._dll_directories = []

    @property
    def metadata(self) -> dict[str, object]:
        return {
            "provider": "gigaam_onnx", "model": "v3_rnnt", "precision": "fp32",
            "revision": MODEL_REVISION, "device": self._selected_device or self._device,
            "warmed_up": self._warmed_up, "warmup_duration_ms": self._warmup_duration_ms,
            "fallback_reason": self._fallback_reason,
        }

    def _prepare_model_files(self) -> None:
        if all((self._model_dir / name).is_file() for name in MODEL_FILES):
            return
        from huggingface_hub import snapshot_download

        snapshot_download("istupakov/gigaam-v3-onnx", revision=MODEL_REVISION,
                          local_dir=str(self._model_dir), allow_patterns=list(MODEL_FILES))

    def _prepare_cuda(self, runtime) -> None:
        if "CUDAExecutionProvider" not in runtime.get_available_providers():
            raise RuntimeError("CUDAExecutionProvider is unavailable in this ONNX Runtime")
        if os.name == "nt":
            import importlib.util

            # Wheels share the nvidia namespace. Keep directory handles alive
            # for delayed library loads throughout the provider's lifetime.
            for name in ("cuda_runtime", "cuda_nvrtc", "cublas", "cufft", "nvjitlink", "cudnn"):
                spec = importlib.util.find_spec(f"nvidia.{name}")
                if spec and spec.submodule_search_locations:
                    for location in spec.submodule_search_locations:
                        directory = Path(location) / "bin"
                        if directory.is_dir():
                            self._dll_directories.append(os.add_dll_directory(str(directory)))
        runtime.preload_dlls(directory="")

    def _load_model(self, device: str):
        import onnx_asr
        import onnxruntime as runtime

        if device == "cuda":
            self._prepare_cuda(runtime)
        options = runtime.SessionOptions()
        options.intra_op_num_threads = self._threads if device == "cuda" else self._cpu_threads
        options.inter_op_num_threads = 1
        options.log_severity_level = 3
        options.add_session_config_entry("session.intra_op.allow_spinning", "0")
        provider = "CUDAExecutionProvider" if device == "cuda" else "CPUExecutionProvider"
        model = onnx_asr.load_model(
            "gigaam-v3-rnnt", self._model_dir, quantization=None,
            providers=[provider], sess_options=options,
            preprocessor_config={"providers": ["CPUExecutionProvider"], "sess_options": options},
            resampler_config={"providers": ["CPUExecutionProvider"], "sess_options": options},
        )
        # These session names are part of the pinned onnx-asr 0.12.0 adapter.
        sessions = [getattr(model.asr, name) for name in ("_encoder", "_decoder", "_joiner")]
        if any(provider not in session.get_providers() for session in sessions):
            raise RuntimeError(f"Requested {provider} did not initialize")
        for session in sessions:
            session.disable_fallback()
        return model

    def _ensure_model(self) -> None:
        if self._model is not None:
            return
        self._prepare_model_files()
        candidates = ["cuda", "cpu"] if self._device == "auto" else [self._device]
        for device in candidates:
            try:
                self._model = self._load_model(device)
                self._selected_device = device
                logger.info("GigaAM ONNX loaded: device=%s precision=fp32", device)
                return
            except Exception as exc:
                if device != "cuda" or self._device != "auto":
                    raise
                self._fallback_reason = "cuda_initialization_failed"
                logger.info("GigaAM ONNX CUDA unavailable, loading CPU: error_type=%s", type(exc).__name__)
                gc.collect()

    def _recognize(self, audio: Pcm16Audio, split: bool = True) -> str:
        import numpy as np

        if not audio.data:
            return ""
        chunks = self._chunker._split_pcm16_on_quiet(audio.data, overlap_seconds=.75) if split else [audio.data]
        texts = [self._model.recognize(
            np.frombuffer(chunk, dtype="<i2").astype(np.float32) / 32768,
            sample_rate=16000,
        ) for chunk in chunks]
        return self._chunker._merge_overlapped_texts(texts)

    def _infer(self, audio: Pcm16Audio, split: bool = True) -> str:
        self._ensure_model()
        try:
            return self._recognize(audio, split)
        except Exception as exc:
            if self._device != "auto" or self._selected_device != "cuda":
                raise
            message = str(exc).lower()
            if not any(word in message for word in ("cuda", "cublas", "cudnn", "out of memory", "driver")):
                raise
            logger.info("GigaAM ONNX retrying utterance on CPU: error_type=%s", type(exc).__name__)
            self._fallback_reason = "cuda_inference_failed"
            self._model = None
            gc.collect()
            self._model = self._load_model("cpu")
            self._selected_device = "cpu"
            return self._recognize(audio, split)

    def _preload_sync(self) -> None:
        with self._lock:
            if self._warmed_up:
                return
            started = time.perf_counter()
            self._infer(Pcm16Audio(b"\x00\x00" * 6400))
            self._warmup_duration_ms = int((time.perf_counter() - started) * 1000)
            self._warmed_up = True

    async def preload(self) -> None:
        await asyncio.to_thread(self._preload_sync)

    def _transcribe_sync(self, audio: Pcm16Audio, language: str, started: float, split: bool = True) -> STTResult:
        with self._lock:
            text = self._infer(audio, split)
        return STTResult(text=text, language="ru" if language == "auto" else language,
                         duration_ms=int((time.perf_counter() - started) * 1000),
                         provider="gigaam_onnx", model="v3_rnnt")

    async def transcribe_pcm16(self, audio: Pcm16Audio, language: str) -> STTResult:
        started = time.perf_counter()
        return await asyncio.to_thread(self._transcribe_sync, audio, language, started)

    async def transcribe(self, audio_path: Path, language: str) -> STTResult:
        audio = await asyncio.to_thread(decode_audio_file, audio_path)
        return await self.transcribe_pcm16(audio, language)

    def start_live(self):
        return LiveGigaAMTranscription(self)

    async def transcribe_chunk(self, audio: Pcm16Audio, language: str) -> STTResult:
        # Already partitioned by the batch quiet-cut algorithm, including its
        # overlap. Do not split the final <=24.75 s chunk a second time.
        return await asyncio.to_thread(self._transcribe_sync, audio, language, time.perf_counter(), False)


class LiveGigaAMTranscription:
    """Precompute stable batch chunks while speech continues, without publishing text.

    The quiet cut searches up to 23 s and reserves a 5 s tail. Only a 28 s
    prefix is therefore stable independently of later audio. At stop, exact
    chunk-byte equality decides which results can be reused; altered or trimmed
    audio falls back to normal inference rather than trusting stale text.
    """

    def __init__(self, provider: GigaAMOnnxSTTProvider) -> None:
        self.provider = provider
        self.cursor = 0
        self.cached: list[tuple[bytes, str]] = []
        self.task: asyncio.Task | None = None
        self.failed = False
        self.closed = False
        self.reused_chunks = 0

    def update(self, pcm16: bytearray) -> None:
        if self.closed or self.failed or (self.task is not None and not self.task.done()):
            return
        if len(pcm16) - self.cursor < 28 * 32000:
            return
        # A completed candidate can be replaced/resumed by input management.
        # Prefix mismatch invalidates speculative work before reusing it.
        if self.cached and not bytes(pcm16[:len(self.cached[0][0])]) == self.cached[0][0]:
            self.failed = True
            return
        preview = bytes(pcm16[self.cursor:self.cursor + 28 * 32000])
        first = self.provider._chunker._split_pcm16_on_quiet(preview, overlap_seconds=.75)[0]
        end = self.cursor + len(first)
        chunk = bytes(pcm16[max(0, self.cursor - 24000):end])
        self.task = asyncio.create_task(self._precompute(chunk, end), name="voice-stt-precompute")

    async def _precompute(self, chunk: bytes, end: int) -> None:
        try:
            result = await self.provider.transcribe_chunk(Pcm16Audio(chunk), "ru")
            if not self.closed:
                self.cached.append((chunk, result.text))
                self.cursor = end
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.failed = True
            logger.info("Live STT precompute failed; final batch will retry: error_type=%s", type(exc).__name__)

    async def finish(self, audio: Pcm16Audio, language: str) -> STTResult:
        started = time.perf_counter()
        if self.task is not None:
            await asyncio.shield(self.task)
        chunks = self.provider._chunker._split_pcm16_on_quiet(audio.data, overlap_seconds=.75)
        texts = []
        self.reused_chunks = 0
        for index, chunk in enumerate(chunks):
            if not self.failed and index < len(self.cached) and self.cached[index][0] == chunk:
                texts.append(self.cached[index][1])
                self.reused_chunks += 1
            else:
                result = await self.provider.transcribe_chunk(Pcm16Audio(chunk), language)
                texts.append(result.text)
        return STTResult(text=self.provider._chunker._merge_overlapped_texts(texts),
                         language="ru" if language == "auto" else language,
                         duration_ms=int((time.perf_counter() - started) * 1000),
                         provider="gigaam_onnx", model="v3_rnnt")

    async def close(self) -> None:
        self.closed = True
        if self.task is not None:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
        self.cached.clear()
