import asyncio
import sqlite3
from types import SimpleNamespace

import numpy as np
import pytest

from apps.backend.app.conversation.adjudicator import AdjudicationResult
from apps.backend.app.conversation.schemas import ConversationAction, EventAppraisal
from apps.backend.app.conversation.service import LiveConversationService
from apps.backend.app.conversation.state_service import CharacterStateService
from apps.backend.app.storage.timeline import TimelineStore
from apps.backend.app.voice.audio import Pcm16Audio
from apps.backend.app.voice.gigaam_onnx import GigaAMOnnxSTTProvider
from apps.backend.app.voice.providers import STTResult


def runtime(**overrides):
    return SimpleNamespace(**{
        "memory_incognito": False,
        "live_conversation_mood_recovery": "natural",
        "live_conversation_engagement": "balanced",
        "live_conversation_participant_mode": "one_to_one",
        "live_conversation_address_strictness": "balanced",
        "live_conversation_echo_mode": "auto", **overrides,
    })


def delayed_appraisal(monkeypatch, service):
    started, release = asyncio.Event(), asyncio.Event()

    async def adjudicate(_transcript, **kwargs):
        started.set()
        await release.wait()
        return AdjudicationResult(
            kwargs["fallback_decision"],
            EventAppraisal(event_kind="praise", confidence=.9, intensity=.6,
                          valence=.5, emotion_impulses={"joy": .6},
                          cause_message_ids=[kwargs["cause_message_id"]]), "llm",
        )

    monkeypatch.setattr(service._adjudicator, "adjudicate", adjudicate)
    return started, release


@pytest.mark.anyio
async def test_private_reply_starts_before_model_appraisal_and_applies_it_once(tmp_path, monkeypatch):
    store = TimelineStore(tmp_path / "timeline.sqlite3")
    store.init_db()
    state = CharacterStateService(store)
    service = LiveConversationService(store, runtime(), llm_provider=object(),
                                      state_service=state, parallel_appraisal=True)
    started, release = delayed_appraisal(monkeypatch, service)
    generation = await service.speech_started("session")
    result = await asyncio.wait_for(service.ingest_observation(
        session_id="session", transcript="Ирис, ты меня выручила, спасибо!",
        language="ru", expected_generation=generation,
    ), .5)
    await started.wait()
    assert result.decision.action is ConversationAction.RESPOND
    assert state.current().affect.joy == 0
    assert service.debug("session")["last_decision_source"] == "deterministic_parallel_appraisal"
    completion = asyncio.create_task(service.finish_appraisal("session", generation))
    await asyncio.sleep(0)
    assert not completion.done()
    release.set()
    await completion
    assert state.current().affect.joy > 0
    with sqlite3.connect(tmp_path / "timeline.sqlite3") as connection:
        assert connection.execute("SELECT count(*) FROM character_state_events").fetchone()[0] == 1
    retry = state.prepare(transcript="повтор", message_id=result.message.id,
                          appraisal=EventAppraisal(confidence=.9))
    assert retry.state_applied is False


@pytest.mark.anyio
async def test_new_speech_cancels_parallel_appraisal_without_stale_state(tmp_path, monkeypatch):
    store = TimelineStore(tmp_path / "timeline.sqlite3")
    store.init_db()
    state = CharacterStateService(store)
    service = LiveConversationService(store, runtime(), llm_provider=object(),
                                      state_service=state, parallel_appraisal=True)
    started, release = delayed_appraisal(monkeypatch, service)
    await service.ingest_observation(session_id="session", transcript="Ирис, спасибо!", language="ru")
    await started.wait()
    await service.speech_started("session")
    release.set()
    assert service.debug("session")["active_tasks"] == []
    assert state.current().affect.joy == 0


@pytest.mark.anyio
@pytest.mark.parametrize("overrides,transcript,uncertain", [
    ({"live_conversation_participant_mode": "group"}, "Ирис, что думаешь?", False),
    ({}, "Ирис, говори без мата", False),
    ({}, "Ирис, не используй ненормативную лексику", False),
    ({}, "Ирис, что думаешь?", True),
])
async def test_sensitive_decisions_still_wait_for_appraisal(tmp_path, monkeypatch, overrides, transcript, uncertain):
    store = TimelineStore(tmp_path / "timeline.sqlite3")
    store.init_db()
    service = LiveConversationService(store, runtime(**overrides), llm_provider=object(),
                                      parallel_appraisal=True)
    started, release = delayed_appraisal(monkeypatch, service)
    ingest = asyncio.create_task(service.ingest_observation(
        session_id="session", transcript=transcript, language="ru", stt_uncertain=uncertain,
    ))
    await asyncio.wait_for(started.wait(), .5)
    assert not ingest.done()
    release.set()
    await ingest
    assert service.debug("session")["last_decision_source"] == "llm"


@pytest.mark.anyio
async def test_parallel_appraisal_in_incognito_never_persists_state_or_messages(tmp_path, monkeypatch):
    store = TimelineStore(tmp_path / "timeline.sqlite3")
    store.init_db()
    service = LiveConversationService(store, runtime(memory_incognito=True),
                                      llm_provider=object(), parallel_appraisal=True)
    started, release = delayed_appraisal(monkeypatch, service)
    result = await service.ingest_observation(session_id="session", transcript="Ирис, спасибо!", language="ru")
    assert result.message is None
    await started.wait()
    release.set()
    await service.finish_appraisal("session", result.generation)
    with sqlite3.connect(tmp_path / "timeline.sqlite3") as connection:
        for table in ("conversation_messages", "character_state_events", "character_state_snapshots"):
            assert connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 0


def fake_stt(tmp_path, monkeypatch):
    provider = GigaAMOnnxSTTProvider("v3_rnnt", "cpu", tmp_path)
    calls = []

    async def transcribe(audio, language):
        import hashlib
        calls.append(audio.data)
        return STTResult(text=hashlib.sha256(audio.data).hexdigest(), language=language,
                         provider="test", model="test", duration_ms=0)

    monkeypatch.setattr(provider, "transcribe_chunk", transcribe)
    return provider, calls


@pytest.mark.anyio
@pytest.mark.parametrize("seconds", [12, 28, 33, 61, 130])
async def test_precompute_reuses_exact_batch_chunks_and_preserves_text(tmp_path, monkeypatch, seconds):
    provider, calls = fake_stt(tmp_path, monkeypatch)
    audio = Pcm16Audio(np.random.default_rng(42).integers(-3000, 3000, seconds * 16000,
                                                         dtype=np.int16).tobytes())
    stream = provider.start_live()
    for end in range(32000, len(audio.data) + 1, 32000):
        stream.update(bytearray(audio.data[:end]))
        if stream.task is not None:
            await stream.task
    batch_chunks = provider._chunker._split_pcm16_on_quiet(audio.data, overlap_seconds=.75)
    result = await stream.finish(audio, "ru")
    assert calls == batch_chunks
    assert stream.reused_chunks == (0 if seconds < 28 else len(batch_chunks) - 1)
    import hashlib
    assert result.text == " ".join(hashlib.sha256(chunk).hexdigest() for chunk in batch_chunks)
    await stream.close()
    assert stream.cached == []


@pytest.mark.anyio
async def test_changed_audio_never_reuses_stale_transcript(tmp_path, monkeypatch):
    provider, calls = fake_stt(tmp_path, monkeypatch)
    audio = Pcm16Audio(b"\0\0" * 16000 * 33)
    stream = provider.start_live()
    stream.update(bytearray(audio.data))
    await stream.task
    changed = Pcm16Audio(b"\1\0" + audio.data[2:])
    await stream.finish(changed, "ru")
    assert stream.reused_chunks == 0
    assert calls[1:] == provider._chunker._split_pcm16_on_quiet(changed.data, overlap_seconds=.75)
    await stream.close()


@pytest.mark.anyio
async def test_background_failure_retries_full_batch_and_close_cancels_worker(tmp_path, monkeypatch):
    provider, calls = fake_stt(tmp_path, monkeypatch)
    original = provider.transcribe_chunk

    async def fail_once(audio, language):
        monkeypatch.setattr(provider, "transcribe_chunk", original)
        raise RuntimeError("inference failure")

    monkeypatch.setattr(provider, "transcribe_chunk", fail_once)
    stream = provider.start_live()
    audio = Pcm16Audio(b"\0\0" * 16000 * 33)
    stream.update(bytearray(audio.data))
    await stream.task
    await stream.finish(audio, "ru")
    assert stream.failed and stream.reused_chunks == 0
    assert len(calls) == 2
    await stream.close()

    started = asyncio.Event()

    async def blocked(*args):
        started.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(provider, "transcribe_chunk", blocked)
    stream = provider.start_live()
    stream.update(bytearray(audio.data))
    await started.wait()
    await asyncio.wait_for(stream.close(), .5)
    assert stream.task.cancelled()
