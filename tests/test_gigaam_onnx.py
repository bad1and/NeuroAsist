import asyncio
from types import SimpleNamespace

import numpy as np
import pytest

from apps.backend.app.core.config import Settings
from apps.backend.app.voice.audio import Pcm16Audio, write_pcm16_wav
from apps.backend.app.voice.gigaam_onnx import GigaAMOnnxSTTProvider, MODEL_FILES, MODEL_REVISION
from apps.backend.app.voice.service import VoiceService


def provider(tmp_path, monkeypatch, device="auto"):
    instance = GigaAMOnnxSTTProvider("v3_rnnt", device, tmp_path)
    monkeypatch.setattr(instance, "_prepare_model_files", lambda: None)
    return instance


def test_service_selects_onnx_with_configured_model_path(tmp_path):
    settings = Settings(voice_stt_provider="gigaam_onnx", voice_stt_device="auto",
                        voice_stt_onnx_model_path=str(tmp_path), voice_tts_provider="mock")
    service = VoiceService(settings)
    assert isinstance(service.stt_provider, GigaAMOnnxSTTProvider)
    assert service.stt_provider._model_dir == tmp_path


def test_model_download_is_pinned_and_only_requests_fp32(tmp_path, monkeypatch):
    import sys

    calls = []
    monkeypatch.setitem(sys.modules, "huggingface_hub", SimpleNamespace(
        snapshot_download=lambda *args, **kwargs: calls.append((args, kwargs))))
    instance = GigaAMOnnxSTTProvider("v3_rnnt", "cpu", tmp_path)
    instance._prepare_model_files()
    assert calls[0][1]["revision"] == MODEL_REVISION
    assert calls[0][1]["allow_patterns"] == list(MODEL_FILES)
    for name in MODEL_FILES:
        (tmp_path / name).touch()
    instance._prepare_model_files()
    assert len(calls) == 1


def test_auto_recovers_from_cuda_initialization_failure(tmp_path, monkeypatch):
    instance = provider(tmp_path, monkeypatch)
    loads = []

    def load(device):
        loads.append(device)
        if device == "cuda":
            raise RuntimeError("CUDA DLL missing")
        return SimpleNamespace(recognize=lambda *args, **kwargs: "Привет")

    monkeypatch.setattr(instance, "_load_model", load)
    result = asyncio.run(instance.transcribe_pcm16(Pcm16Audio(b"\0\0" * 6400), "auto"))
    assert loads == ["cuda", "cpu"]
    assert result.text == "Привет" and result.language == "ru"
    assert result.provider == "gigaam_onnx"
    assert instance.metadata["device"] == "cpu"
    assert instance.metadata["fallback_reason"] == "cuda_initialization_failed"


def test_cuda_oom_retries_the_entire_same_utterance_and_stays_on_cpu(tmp_path, monkeypatch):
    instance = provider(tmp_path, monkeypatch)
    inputs, loads = [], []

    def load(device):
        loads.append(device)

        def recognize(samples, **kwargs):
            inputs.append((device, samples.copy()))
            if device == "cuda":
                raise RuntimeError("CUDA out of memory")
            return "Один два"

        return SimpleNamespace(recognize=recognize)

    monkeypatch.setattr(instance, "_load_model", load)
    audio = Pcm16Audio(np.array([0, 32767, -32768] * 5000, dtype="<i2").tobytes())
    assert asyncio.run(instance.transcribe_pcm16(audio, "ru")).text == "Один два"
    assert loads == ["cuda", "cpu"]
    np.testing.assert_array_equal(inputs[0][1], inputs[1][1])
    asyncio.run(instance.transcribe_pcm16(audio, "ru"))
    assert loads == ["cuda", "cpu"]
    assert instance.metadata["fallback_reason"] == "cuda_inference_failed"


@pytest.mark.parametrize("device,message", [("cuda", "CUDA failed"), ("auto", "bad input shape")])
def test_explicit_cuda_or_unrelated_error_is_not_silently_hidden(tmp_path, monkeypatch, device, message):
    instance = provider(tmp_path, monkeypatch, device)
    loads = []

    def recognize(*args, **kwargs):
        raise RuntimeError(message)

    monkeypatch.setattr(instance, "_load_model", lambda selected: loads.append(selected) or
                        SimpleNamespace(recognize=recognize))
    with pytest.raises(RuntimeError, match=message):
        asyncio.run(instance.transcribe_pcm16(Pcm16Audio(b"\0\0" * 6400), "ru"))
    assert loads == ["cuda"]


def test_preload_exercises_inference_and_cpu_recovery_once(tmp_path, monkeypatch):
    instance = provider(tmp_path, monkeypatch)
    calls = []

    def load(device):
        def recognize(*args, **kwargs):
            calls.append(device)
            if device == "cuda":
                raise RuntimeError("cuDNN convolution unsupported")
            return ""
        return SimpleNamespace(recognize=recognize)

    monkeypatch.setattr(instance, "_load_model", load)
    asyncio.run(instance.preload())
    asyncio.run(instance.preload())
    assert calls == ["cuda", "cpu"]
    assert instance.metadata["warmed_up"] is True
    assert instance.metadata["device"] == "cpu"


def test_long_pcm_and_file_path_share_overlap_merge_without_microphone_temp_files(tmp_path, monkeypatch):
    instance = provider(tmp_path, monkeypatch, "cpu")
    pieces = []

    def recognize(samples, **kwargs):
        pieces.append(len(samples))
        return "привет мир" if len(pieces) % 2 else "мир проверка"

    monkeypatch.setattr(instance, "_load_model", lambda device: SimpleNamespace(recognize=recognize))
    audio = Pcm16Audio(b"\0\0" * (16000 * 30))
    pcm_result = asyncio.run(instance.transcribe_pcm16(audio, "ru"))
    assert pcm_result.text == "привет мир проверка"
    assert len(pieces) == 2 and max(pieces) <= 16000 * 24
    path = tmp_path / "upload.wav"
    write_pcm16_wav(path, audio)
    file_result = asyncio.run(instance.transcribe(path, "ru"))
    assert file_result.text == pcm_result.text


def test_loader_rejects_silent_cuda_fallback_and_disables_runtime_fallback(tmp_path, monkeypatch):
    import sys

    instance = provider(tmp_path, monkeypatch)
    sessions = []
    options = []

    class SessionOptions:
        def add_session_config_entry(self, *args):
            pass

    class Session:
        disabled = False
        def get_providers(self):
            return ["CPUExecutionProvider"]
        def disable_fallback(self):
            self.disabled = True

    def load_model(*args, **kwargs):
        options.append(kwargs)
        current = [Session(), Session(), Session()]
        sessions.extend(current)
        return SimpleNamespace(asr=SimpleNamespace(
            _encoder=current[0], _decoder=current[1], _joiner=current[2]))

    monkeypatch.setitem(sys.modules, "onnx_asr", SimpleNamespace(load_model=load_model))
    monkeypatch.setitem(sys.modules, "onnxruntime", SimpleNamespace(SessionOptions=SessionOptions))
    monkeypatch.setattr(instance, "_prepare_cuda", lambda runtime: None)
    instance._ensure_model()
    assert instance.metadata["device"] == "cpu"
    assert [row["providers"] for row in options] == [["CUDAExecutionProvider"], ["CPUExecutionProvider"]]
    assert all(session.disabled for session in sessions[3:])
    assert options[1]["sess_options"].intra_op_num_threads == 8
    assert options[1]["preprocessor_config"]["providers"] == ["CPUExecutionProvider"]


def test_dependency_graph_accepts_gpu_distribution_for_transitive_cpu_requirement():
    from scripts.check_python_dependencies import resolved_closure

    installed = {
        "consumer": SimpleNamespace(requires=["onnxruntime>=1.18"]),
        "onnxruntime-gpu": SimpleNamespace(requires=["numpy>=1.22"]),
        "numpy": SimpleNamespace(requires=[]),
    }
    closure, missing = resolved_closure({"consumer"}, installed,
                                        {"onnxruntime": "onnxruntime-gpu"})
    assert closure == {"consumer", "onnxruntime-gpu", "numpy"}
    assert missing == []
    assert resolved_closure({"consumer"}, installed)[1] == ["onnxruntime"]
