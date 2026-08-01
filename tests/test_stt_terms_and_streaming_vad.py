from pathlib import Path

import torch
import pytest

from apps.backend.app.voice.input import SileroVadProvider, SileroVadStream
from apps.backend.app.voice.stt_terms import correct_stt_terms, load_stt_terms, save_stt_terms


class FakeSilero:
    def __init__(self, probability: float = .8) -> None:
        self.probability = probability
        self.calls = 0
        self.resets = 0

    def __call__(self, audio, sample_rate):
        assert sample_rate == 16_000
        assert audio.shape[-1] == 512
        self.calls += 1
        return torch.tensor(self.probability)

    def reset_states(self) -> None:
        self.resets += 1


def test_silero_buffers_partial_windows_and_resets_state() -> None:
    model = FakeSilero()
    stream = SileroVadStream(model, torch)

    assert stream.feed(b"\x01\x00" * 511) == []
    observations = stream.feed(b"\x01\x00")
    assert len(observations) == 1
    assert observations[0].samples == 512
    assert observations[0].value == pytest.approx(.8)
    assert model.calls == 1

    stream.reset()
    assert model.resets == 2
    assert stream.feed(b"\x01\x00") == []


def test_silero_streams_do_not_share_model_state() -> None:
    first = FakeSilero(.7)
    second = FakeSilero(.2)
    first_stream = SileroVadStream(first, torch)
    second_stream = SileroVadStream(second, torch)

    assert first_stream.feed(b"\x00\x00" * 512)[0].value == pytest.approx(.7)
    assert second_stream.feed(b"\x00\x00" * 512)[0].value == pytest.approx(.2)
    assert first.calls == second.calls == 1


def test_packaged_silero_is_ready_without_managed_model() -> None:
    provider = SileroVadProvider(None)

    assert provider.ready is True
    assert provider.version == "6.2.1"
    stream = provider.create_stream()
    observations = stream.feed(b"\x00\x00" * 512)
    assert len(observations) == 1


def test_stt_terms_use_longest_exact_unicode_boundaries_without_fuzzy() -> None:
    terms = {
        "NeuroAsist": ["нейро асист", "нейро"],
        "GitHub": ["гит хаб"],
    }
    result = correct_stt_terms(
        "Открой нейро асист и гит хаб, но не меняй нейрон и гитхабчик.",
        terms,
    )

    assert result.text == "Открой NeuroAsist и GitHub, но не меняй нейрон и гитхабчик."
    assert [item.source for item in result.replacements] == ["нейро асист", "гит хаб"]


def test_stt_terms_round_trip_separately_from_tts_dictionary(tmp_path: Path) -> None:
    path = tmp_path / "stt-terms.json"
    saved = save_stt_terms(path, {"GigaAM": ["гига ам", "гигаэм"]})

    assert saved == {"GigaAM": ["гига ам", "гигаэм"]}
    assert load_stt_terms(path) == saved
