from __future__ import annotations

import asyncio
import contextlib
import re
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime
from difflib import SequenceMatcher
from typing import Awaitable, Callable
from uuid import uuid4

from apps.backend.app.conversation.adjudicator import StructuredConversationAdjudicator
from apps.backend.app.conversation.behavior import StateToBehaviorRenderer
from apps.backend.app.conversation.decision import ConversationDecisionEngine, DecisionContext
from apps.backend.app.conversation.schemas import (
    ConversationAction,
    ConversationDecision,
    ConversationPhase,
    DecisionReason,
    SpeakerRole,
    SpeakerRoleEstimate,
)
from apps.backend.app.conversation.speaker import SpeakerRoleEstimator
from apps.backend.app.conversation.state import AffectState, CharacterStateReducer, ParticipantState
from apps.backend.app.conversation.state_service import CharacterStateService
from apps.backend.app.storage.timeline import PRIMARY_RELATIONSHIP_ID, StoredTimelineMessage, TimelineStore


EventSender = Callable[[dict[str, object]], Awaitable[None]]
AvatarReactionHandler = Callable[[str, str, float, int], Awaitable[None]]
DeferredResponseHandler = Callable[
    [str, "DeferredReaction", int, str],
    Awaitable[None],
]


@dataclass
class DeferredReaction:
    id: str
    trigger_message_ids: list[str]
    topic_key: str
    earliest_at: float
    expires_at: float
    minimum_silence_ms: int
    required_score: float
    generation_created: int
    transcript: str
    language: str
    source_message_id: str | None
    state_context: str
    attempts: int = 0


@dataclass
class PlaybackSegment:
    text: str
    started_at: float
    utterance_id: str | None = None
    generation: int | None = None
    finished_at: float | None = None


@dataclass
class SpokenWindow:
    finished_at: float
    duration_seconds: float
    initiative: bool


@dataclass
class ConversationSession:
    session_id: str
    mode: str = "live"
    phase: ConversationPhase = ConversationPhase.IDLE
    generation: int = 0
    active_turn_id: str | None = None
    active_utterance_id: str | None = None
    recent_observations: deque[dict[str, object]] = field(default_factory=lambda: deque(maxlen=20))
    active_tasks: set[asyncio.Task] = field(default_factory=set)
    task_details: dict[asyncio.Task, dict[str, object]] = field(default_factory=dict)
    deferred_reactions: deque[DeferredReaction] = field(default_factory=lambda: deque(maxlen=3))
    playback_segments: deque[PlaybackSegment] = field(default_factory=lambda: deque(maxlen=8))
    spoken_windows: deque[SpokenWindow] = field(default_factory=lambda: deque(maxlen=200))
    committed_assistant_utterances: set[str] = field(default_factory=set)
    live_utterance_ids: set[str] = field(default_factory=set)
    utterance_generations: dict[str, int] = field(default_factory=dict)
    acknowledged_prefixes: dict[str, list[str]] = field(default_factory=dict)
    generated_assistant_replies: dict[str, str] = field(default_factory=dict)
    last_generated_assistant_reply: str = ""
    initiative_timestamps: deque[float] = field(default_factory=lambda: deque(maxlen=20))
    backchannel_timestamps: deque[float] = field(default_factory=lambda: deque(maxlen=20))
    initiative_utterance_ids: set[str] = field(default_factory=set)
    last_human_activity_at: float = 0.0
    last_iris_activity_at: float = 0.0
    other_conversation_until: float = 0.0
    last_decision: ConversationDecision | None = None
    last_decision_source: str = "deterministic"
    last_speaker_estimate: SpeakerRoleEstimate | None = None
    last_cancellation: dict[str, object] | None = None
    event_sender: EventSender | None = None
    affect: AffectState = field(default_factory=AffectState)
    participants: dict[str, ParticipantState] = field(
        default_factory=lambda: {"primary": ParticipantState()}
    )
    relationship_budget_day: str = field(default_factory=lambda: datetime.now(UTC).date().isoformat())
    daily_relationship_deltas: dict[str, float] = field(default_factory=dict)
    recent_event_counts: dict[str, int] = field(default_factory=dict)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


@dataclass(frozen=True)
class ObservationResult:
    message: StoredTimelineMessage | None
    decision: ConversationDecision
    generation: int
    turn_id: str
    utterance_id: str
    state_context: str


class LiveConversationService:
    """Per-session observation-first conversation orchestrator."""

    def __init__(
        self,
        store: TimelineStore,
        runtime_settings,
        *,
        memory_service=None,
        event_publisher=None,
        llm_provider=None,
        state_service: CharacterStateService | None = None,
    ) -> None:
        self._store = store
        self._runtime = runtime_settings
        self._memory_service = memory_service
        self._publish = event_publisher
        self._sessions: dict[str, ConversationSession] = {}
        self._decision = ConversationDecisionEngine()
        self._adjudicator = StructuredConversationAdjudicator(llm_provider)
        self._speaker = SpeakerRoleEstimator()
        self._reducer = CharacterStateReducer()
        self._state_service = state_service
        self._turn_detector = None
        self._stt_semaphore = asyncio.Semaphore(2)
        self._decision_semaphore = asyncio.Semaphore(4)
        self._avatar_reaction_handler: AvatarReactionHandler | None = None
        self._deferred_response_handler: DeferredResponseHandler | None = None

    def session(self, session_id: str) -> ConversationSession:
        session = self._sessions.get(session_id)
        if session is None:
            session = ConversationSession(session_id=session_id)
            self._restore_state(session)
            self._sessions[session_id] = session
        return session

    def bind_turn_detector(self, detector) -> None:
        self._turn_detector = detector

    def bind_action_handlers(
        self,
        *,
        avatar_reaction: AvatarReactionHandler | None = None,
        deferred_response: DeferredResponseHandler | None = None,
    ) -> None:
        self._avatar_reaction_handler = avatar_reaction
        self._deferred_response_handler = deferred_response

    async def speech_started(self, session_id: str, send: EventSender | None = None) -> int:
        session = self.session(session_id)
        async with session.lock:
            if send is not None:
                session.event_sender = send
            interrupted: list[tuple[str, str, int, str]] = []
            for utterance_id in session.live_utterance_ids:
                if utterance_id in session.committed_assistant_utterances:
                    continue
                generated = session.generated_assistant_replies.get(utterance_id, "").strip()
                acknowledged = " ".join(
                    session.acknowledged_prefixes.get(utterance_id, [])
                ).strip()
                content = generated or acknowledged
                if not content:
                    continue
                # Generated text was already visible in the chat even when
                # playback had not started. It is a completed conversational
                # turn; playback-only prefixes remain interrupted.
                status = "completed" if generated else "interrupted"
                interrupted.append((
                    utterance_id,
                    content,
                    session.utterance_generations.get(utterance_id, session.generation),
                    status,
                ))
            for utterance_id, _, _, _ in interrupted:
                session.committed_assistant_utterances.add(utterance_id)
            session.generation += 1
            session.phase = ConversationPhase.LISTENING
            session.last_human_activity_at = time.monotonic()
            generation = session.generation
            cancelled_tasks = 0
            for task in tuple(session.active_tasks):
                if not task.done():
                    task.cancel()
                    cancelled_tasks += 1
            session.active_tasks.clear()
            session.task_details.clear()
            discarded_deferred = len(session.deferred_reactions)
            session.deferred_reactions.clear()
            if any(item[0] in session.initiative_utterance_ids for item in interrupted):
                session.last_iris_activity_at = time.monotonic() + 120.0
            session.last_cancellation = {
                "generation": generation,
                "reason": "human_speech_started",
                "cancelled_tasks": cancelled_tasks,
                "discarded_deferred": discarded_deferred,
            }
        for utterance_id, prefix, utterance_generation, status in interrupted:
            self._commit_assistant(
                session,
                utterance_id,
                prefix,
                utterance_generation,
                status=status,
            )
        if send is not None:
            await send(self._event(session, "conversation.phase", payload={"phase": session.phase.value}))
            if cancelled_tasks or discarded_deferred:
                await send(
                    self._event(
                        session,
                        "conversation.cancelled",
                        payload={
                            "reason": "human_speech_started",
                            "cancelled_tasks": cancelled_tasks,
                            "discarded_deferred": discarded_deferred,
                        },
                    )
                )
        return generation

    async def phase(
        self,
        session_id: str,
        phase: ConversationPhase,
        send: EventSender | None = None,
    ) -> int:
        session = self.session(session_id)
        async with session.lock:
            session.phase = phase
            generation = session.generation
        if send is not None:
            await send(self._event(session, "conversation.phase", payload={"phase": phase.value}))
        return generation

    async def ingest_observation(
        self,
        *,
        session_id: str,
        transcript: str,
        language: str,
        send: EventSender | None = None,
        corrected_content: str | None = None,
        speaker_role: SpeakerRole = SpeakerRole.PRIMARY,
        speaker_confidence: float = 0.9,
        end_of_turn_confidence: float = 1.0,
        stt_uncertain: bool = False,
        expected_generation: int | None = None,
    ) -> ObservationResult:
        session = self.session(session_id)
        transcript = transcript.strip()
        if not transcript:
            raise ValueError("Conversation observation cannot be empty")
        async with session.lock:
            generation = session.generation
            turn_id = uuid4().hex
            utterance_id = uuid4().hex
            if send is not None:
                session.event_sender = send
            if expected_generation is not None and expected_generation != generation:
                decision = self._decision._decision(
                    ConversationAction.WAIT_MORE,
                    DecisionReason.INCOMPLETE_TURN,
                    1.0,
                    0.0,
                    0.0,
                    0.0,
                )
                return ObservationResult(
                    message=None,
                    decision=decision,
                    generation=expected_generation,
                    turn_id=turn_id,
                    utterance_id=utterance_id,
                    state_context=self._state_context(session, decision),
                )
            session.active_turn_id = turn_id
            session.active_utterance_id = utterance_id
            session.phase = ConversationPhase.DECIDING

        addressedness = self._decision.addressedness(corrected_content or transcript)
        strictness = getattr(self._runtime, "live_conversation_address_strictness", "balanced")
        if strictness == "strict" and addressedness < 0.9:
            addressedness *= 0.65
        elif strictness == "relaxed":
            addressedness = min(1.0, addressedness + 0.12)
        echo = self._is_assistant_echo(session, corrected_content or transcript)
        participant_mode = getattr(
            self._runtime,
            "live_conversation_participant_mode",
            "one_to_one",
        )
        recent_iris_turn = bool(
            session.last_iris_activity_at > 0
            and time.monotonic() - session.last_iris_activity_at <= 45
        )
        addressed_to_other_now = self._decision.is_addressed_to_other(
            corrected_content or transcript
        )
        explicitly_addressed_to_iris = addressedness >= 0.86
        if addressed_to_other_now:
            session.other_conversation_until = time.monotonic() + 45
        elif explicitly_addressed_to_iris:
            session.other_conversation_until = 0.0
        addressed_to_other = bool(
            addressed_to_other_now
            or (
                session.other_conversation_until > time.monotonic()
                and not explicitly_addressed_to_iris
            )
        )
        explicit_implicit_address = self._decision.is_implicit_address(
            corrected_content or transcript
        )
        implicit_address = bool(
            participant_mode == "one_to_one"
            and strictness != "strict"
            and speaker_role is SpeakerRole.PRIMARY
            and not addressed_to_other
            and (explicit_implicit_address or recent_iris_turn)
        )
        if implicit_address:
            addressedness = max(addressedness, 0.82)
        if echo or participant_mode == "group":
            recent_primary = any(
                item.get("speaker_role") == SpeakerRole.PRIMARY.value
                for item in list(session.recent_observations)[-3:]
            )
            estimate = self._speaker.estimate(
                corrected_content or transcript,
                participant_mode=participant_mode,
                addressedness=addressedness,
                echo=echo,
                recent_primary=recent_primary,
            )
            speaker_role = estimate.role
            speaker_confidence = estimate.confidence
        else:
            estimate = SpeakerRoleEstimate(
                role=speaker_role,
                confidence=speaker_confidence,
                reasons=["one_to_one_prior"],
            )
        session.last_speaker_estimate = estimate
        significance = self._significance(transcript)
        metadata: dict[str, object] = {
            "speaker_role": speaker_role.value,
            "speaker_confidence": speaker_confidence,
            "speaker_reasons": estimate.reasons,
            "turn_id": turn_id,
            "addressedness": addressedness,
            "addressed_confidence": 0.9 if addressedness >= 0.8 else 0.65,
            "addressing_reasons": (
                ["other_vocative"]
                if addressed_to_other_now
                else ["other_conversation_continuity"]
                if addressed_to_other
                else
                ["implicit_request"]
                if explicit_implicit_address
                else ["recent_iris_turn"]
                if recent_iris_turn and implicit_address
                else []
            ),
            "end_of_turn_confidence": end_of_turn_confidence,
            "stt_uncertain": stt_uncertain,
            "assistant_echo": echo,
            "silent_observation": True,
        }
        message: StoredTimelineMessage | None = None
        if not self._runtime.memory_incognito and not echo:
            message, _ = self._store.append_message(
                role="user",
                content=transcript,
                corrected_content=corrected_content,
                input_mode="voice",
                utterance_id=utterance_id,
                generation=generation,
                turn_id=turn_id,
                language=language,
                metadata=metadata,
            )
            self._store.save_conversation_observation(
                message_id=message.id,
                session_id=session_id,
                turn_id=turn_id,
                utterance_id=utterance_id,
                generation=generation,
                speaker_role=speaker_role.value,
                speaker_confidence=speaker_confidence,
                addressedness=addressedness,
                addressed_confidence=float(metadata["addressed_confidence"]),
                end_of_turn_confidence=end_of_turn_confidence,
                significance=significance,
                metadata=metadata,
            )

        cause_message_id = message.id if message is not None else f"ephemeral-{turn_id}"
        fallback_appraisal = self._decision.appraise(
            corrected_content or transcript,
            cause_message_id,
            "primary" if speaker_role is SpeakerRole.PRIMARY else speaker_role.value,
        )
        context = DecisionContext(
            turn_complete=end_of_turn_confidence >= 0.5,
            speaker_role=speaker_role,
            speaker_confidence=speaker_confidence,
            addressedness=addressedness,
            relevance=0.7 if transcript.rstrip().endswith("?") else 0.45,
            significance=significance,
            social_permission=0.65 if speaker_role is SpeakerRole.PRIMARY else 0.2,
            novelty=0.5,
            turn_confidence=end_of_turn_confidence,
            cooldown_active=self._initiative_cooldown_active(session),
            speech_budget_exceeded=self._speech_budget_exceeded(session),
            engagement=self._runtime.live_conversation_engagement,
            implicit_address=implicit_address,
            addressed_to_other=addressed_to_other,
        )
        fallback_decision = self._decision.decide(
            transcript,
            context,
            affect=session.affect,
            assistant_echo=echo,
        )
        hard_reasons = {
            DecisionReason.INCOMPLETE_TURN,
            DecisionReason.DIRECT_ADDRESS,
            DecisionReason.INVITED,
            DecisionReason.OTHER_PERSON,
            DecisionReason.SELF_TALK,
            DecisionReason.COOLDOWN,
            DecisionReason.SPEECH_BUDGET,
            DecisionReason.ECHO,
        }
        decision = fallback_decision
        appraisal = fallback_appraisal
        decision_source = "deterministic"
        if fallback_decision.reason not in hard_reasons:
            adjudication_task = self._register_task(
                session,
                self._run_adjudication(
                    corrected_content or transcript,
                    fallback_decision=fallback_decision,
                    fallback_appraisal=fallback_appraisal,
                    cause_message_id=cause_message_id,
                    speaker_role=speaker_role.value,
                ),
                name=f"decision-{turn_id}",
                generation=generation,
                reason="ambiguous_observation",
            )
            decision, appraisal, decision_source = await adjudication_task
        if (
            decision.action is ConversationAction.BACKCHANNEL
            and session.backchannel_timestamps
            and time.monotonic() - session.backchannel_timestamps[-1] < 20
        ):
            decision = self._decision._decision(
                ConversationAction.OBSERVE,
                DecisionReason.COOLDOWN,
                0.95,
                decision.addressedness,
                decision.relevance,
                decision.significance,
                decision.reaction_emotion,
            )
            decision_source = f"{decision_source}+backchannel_cooldown"
        if (
            decision.action is ConversationAction.DEFER
            and getattr(self._runtime, "live_conversation_initiative", "rare") == "off"
        ):
            decision = self._decision._decision(
                ConversationAction.OBSERVE,
                DecisionReason.COOLDOWN,
                0.95,
                decision.addressedness,
                decision.relevance,
                decision.significance,
                decision.reaction_emotion,
            )
            decision_source = f"{decision_source}+initiative_disabled"

        async with session.lock:
            stale = generation != session.generation
        relationship_delta: dict[str, float] = {}
        ambient_reasons = {
            DecisionReason.AMBIENT_SPEECH,
            DecisionReason.SELF_TALK,
            DecisionReason.OTHER_PERSON,
            DecisionReason.INCOMPLETE_TURN,
        }
        state_applied = bool(
            not stale
            and not echo
            and decision.reason not in ambient_reasons
            and speaker_role in {SpeakerRole.PRIMARY, SpeakerRole.OTHER}
            and speaker_confidence >= 0.7
        )
        if state_applied:
            if self._state_service is not None and message is not None:
                shared = self._state_service.prepare(
                    transcript=corrected_content or transcript,
                    message_id=message.id,
                    participant_key=appraisal.target_participant,
                    speaker_role=speaker_role,
                    speaker_confidence=speaker_confidence,
                    addressedness=addressedness,
                    stt_uncertain=stt_uncertain,
                    serious=appraisal.serious,
                )
                session.affect = shared.affect
                session.participants[appraisal.target_participant] = shared.relationship
                relationship_delta = {}
                state_applied = shared.state_applied
            else:
                session.affect = self._reducer.decay(
                    session.affect,
                    recovery=self._runtime.live_conversation_mood_recovery,
                )
                self._reducer.apply_affect(session.affect, appraisal)
        if state_applied and self._state_service is None:
            participant = session.participants.setdefault(
                appraisal.target_participant,
                ParticipantState(
                    participant_key=appraisal.target_participant,
                    role=speaker_role.value,
                ),
            )
            today = datetime.now(UTC).date().isoformat()
            if session.relationship_budget_day != today:
                session.relationship_budget_day = today
                session.daily_relationship_deltas.clear()
                session.recent_event_counts.clear()
            repeated_events = session.recent_event_counts.get(appraisal.event_kind, 0)
            participant, relationship_delta = self._reducer.apply_relationship(
                participant,
                appraisal,
                repeated_events=repeated_events,
                daily_delta_used=session.daily_relationship_deltas,
            )
            session.recent_event_counts[appraisal.event_kind] = min(
                8,
                repeated_events + 1,
            )
            for facet, delta in relationship_delta.items():
                session.daily_relationship_deltas[facet] = (
                    session.daily_relationship_deltas.get(facet, 0.0) + abs(delta)
                )
            session.participants[participant.participant_key] = participant

        async with session.lock:
            if generation != session.generation:
                decision = self._decision._decision(
                    ConversationAction.WAIT_MORE,
                    DecisionReason.INCOMPLETE_TURN,
                    1.0,
                    addressedness,
                    context.relevance,
                    significance,
                )
                decision_source = "stale_generation"
            session.last_decision = decision
            session.last_decision_source = decision_source
            if decision.action in {ConversationAction.BACKCHANNEL, ConversationAction.RESPOND}:
                session.live_utterance_ids.add(utterance_id)
                session.utterance_generations[utterance_id] = generation
                if decision.action is ConversationAction.BACKCHANNEL:
                    session.backchannel_timestamps.append(time.monotonic())
            session.phase = (
                ConversationPhase.GENERATING
                if decision.action in {ConversationAction.BACKCHANNEL, ConversationAction.RESPOND}
                else ConversationPhase.LISTENING
            )
            state_context = self._state_context(session, decision)
            deferred: DeferredReaction | None = None
            if decision.action is ConversationAction.DEFER and generation == session.generation:
                deferred = DeferredReaction(
                    id=uuid4().hex,
                    trigger_message_ids=[cause_message_id],
                    topic_key=self._topic_key(corrected_content or transcript),
                    earliest_at=time.monotonic() + max(0.5, (decision.defer_for_ms or 1500) / 1000),
                    expires_at=time.monotonic() + max(1.0, (decision.expires_in_ms or 45_000) / 1000),
                    minimum_silence_ms=max(500, decision.defer_for_ms or 1500),
                    required_score=0.85,
                    generation_created=generation,
                    transcript=corrected_content or transcript,
                    language=language,
                    source_message_id=message.id if message is not None else None,
                    state_context=state_context,
                )
                session.deferred_reactions.append(deferred)
            observation_view = {
                "message_id": message.id if message is not None else None,
                "turn_id": turn_id,
                "generation": generation,
                "speaker_role": speaker_role.value,
                "speaker_confidence": speaker_confidence,
                "speaker_reasons": estimate.reasons,
                "addressedness": addressedness,
                "decision_action": decision.action.value,
                "decision_reason": decision.reason.value,
                "decision_source": decision_source,
            }
            session.recent_observations.append(observation_view)
            session.last_human_activity_at = time.monotonic()

        if message is not None and not stale:
            self._store.set_observation_decision(message.id, decision.action.value, decision.reason.value)
            if state_applied and self._state_service is None:
                self._persist_state(session, appraisal, relationship_delta)
            self._schedule_memory(
                message,
                speaker_role,
                speaker_confidence,
                stt_uncertain,
                decision.reason,
            )
        elif message is not None:
            self._store.set_observation_decision(
                message.id,
                ConversationAction.WAIT_MORE.value,
                DecisionReason.INCOMPLETE_TURN.value,
            )
        if send is not None:
            event_base = {"turn_id": turn_id, "utterance_id": utterance_id}
            if echo:
                await send(self._event(session, "conversation.echo_rejected", **event_base))
            else:
                await send(
                    self._event(
                        session,
                        "conversation.observation",
                        **event_base,
                        payload=observation_view,
                    )
                )
                await send(
                    self._event(
                        session,
                        "conversation.decision",
                        **event_base,
                        payload=decision.model_dump(mode="json"),
                    )
                )
                if decision.action in {ConversationAction.OBSERVE, ConversationAction.WAIT_MORE}:
                    await send(
                        self._event(
                            session,
                            "conversation.silent",
                            **event_base,
                            payload={"action": decision.action.value, "reason": decision.reason.value},
                        )
                    )
                elif decision.action is ConversationAction.AVATAR_REACTION:
                    await send(
                        self._event(
                            session,
                            "conversation.reaction",
                            **event_base,
                            payload={
                                "emotion": decision.reaction_emotion,
                                "nonverbal": True,
                            },
                        )
                    )
                elif decision.action is ConversationAction.DEFER and deferred is not None:
                    await send(
                        self._event(
                            session,
                            "conversation.deferred",
                            **event_base,
                            payload=self._deferred_view(deferred),
                        )
                    )
            await send(
                self._event(
                    session,
                    "conversation.state",
                    **event_base,
                    payload={
                        "affect": session.affect.as_dict(),
                        "display_emotion": self._reducer.display_emotion(session.affect),
                    },
                )
            )
        if (
            decision.action is ConversationAction.AVATAR_REACTION
            and self._avatar_reaction_handler is not None
            and generation == session.generation
        ):
            await self._avatar_reaction_handler(
                session_id,
                decision.reaction_emotion,
                max(0.25, decision.confidence),
                generation,
            )
        if deferred is not None:
            self._register_task(
                session,
                self._run_deferred(session, deferred),
                name=f"deferred-{deferred.id}",
                generation=generation,
                reason="event_driven_deferred_reaction",
            )
        return ObservationResult(
            message=message,
            decision=decision,
            generation=generation,
            turn_id=turn_id,
            utterance_id=utterance_id,
            state_context=state_context,
        )

    async def playback_segment_started(
        self,
        session_id: str,
        text: str,
        utterance_id: str | None = None,
        generation: int | None = None,
    ) -> None:
        session = self.session(session_id)
        async with session.lock:
            expected = session.utterance_generations.get(utterance_id or "")
            if generation is not None and expected is not None and generation != expected:
                return
            session.playback_segments.append(
                PlaybackSegment(
                    text=text,
                    started_at=time.monotonic(),
                    utterance_id=utterance_id,
                    generation=generation,
                )
            )
            session.phase = ConversationPhase.SPEAKING
            session.last_iris_activity_at = time.monotonic()

    async def assistant_text_generated(
        self,
        session_id: str,
        utterance_id: str,
        generation: int,
        text: str,
    ) -> None:
        text = text.strip()
        if not text:
            return
        session = self.session(session_id)
        async with session.lock:
            if (
                utterance_id not in session.live_utterance_ids
                or generation != session.utterance_generations.get(utterance_id)
            ):
                return
            session.generated_assistant_replies[utterance_id] = text
            session.last_generated_assistant_reply = text

    async def playback_segment_finished(
        self,
        session_id: str,
        text: str | None = None,
        utterance_id: str | None = None,
        generation: int | None = None,
    ) -> None:
        session = self.session(session_id)
        async with session.lock:
            if session.playback_segments:
                segment = session.playback_segments[-1]
                if utterance_id and segment.utterance_id not in {None, utterance_id}:
                    return
                segment.finished_at = time.monotonic()
                session.spoken_windows.append(
                    SpokenWindow(
                        finished_at=segment.finished_at,
                        duration_seconds=max(0.0, segment.finished_at - segment.started_at),
                        initiative=bool(
                            utterance_id and utterance_id in session.initiative_utterance_ids
                        ),
                    )
                )
            session.last_iris_activity_at = time.monotonic()
            accepted = bool(
                text
                and utterance_id
                and utterance_id in session.live_utterance_ids
                and utterance_id not in session.committed_assistant_utterances
                and (
                    generation is None
                    or generation == session.utterance_generations.get(utterance_id)
                )
            )
            if accepted:
                session.acknowledged_prefixes.setdefault(utterance_id, []).append(str(text))

    async def playback_finished(self, session_id: str, utterance_id: str | None) -> None:
        if not utterance_id:
            return
        session = self.session(session_id)
        async with session.lock:
            if (
                utterance_id not in session.live_utterance_ids
                or utterance_id in session.committed_assistant_utterances
            ):
                return
            prefix = " ".join(session.acknowledged_prefixes.get(utterance_id, [])).strip()
            if not prefix:
                prefix = session.generated_assistant_replies.get(utterance_id, "").strip()
            if not prefix:
                return
            session.committed_assistant_utterances.add(utterance_id)
            generation = session.utterance_generations.get(utterance_id, session.generation)
        self._commit_assistant(session, utterance_id, prefix, generation, status="completed")

    async def avatar_playback_finished(self, utterance_id: str) -> None:
        for session in tuple(self._sessions.values()):
            if utterance_id in session.live_utterance_ids:
                await self.playback_finished(session.session_id, utterance_id)
                return

    async def close_session(self, session_id: str) -> None:
        session = self._sessions.pop(session_id, None)
        if session is None:
            return
        for task in tuple(session.active_tasks):
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        session.phase = ConversationPhase.CLOSED

    async def close(self) -> None:
        for session_id in tuple(self._sessions):
            await self.close_session(session_id)

    def debug(self, session_id: str) -> dict[str, object]:
        session = self.session(session_id)
        return {
            "session_id": session_id,
            "phase": session.phase.value,
            "generation": session.generation,
            "active_turn_id": session.active_turn_id,
            "active_utterance_id": session.active_utterance_id,
            "recent_observations": list(session.recent_observations),
            "last_decision": session.last_decision.model_dump(mode="json") if session.last_decision else None,
            "last_decision_source": session.last_decision_source,
            "last_speaker_estimate": (
                session.last_speaker_estimate.model_dump(mode="json")
                if session.last_speaker_estimate
                else None
            ),
            "affect": session.affect.as_dict(),
            "participants": {key: value.as_dict() for key, value in session.participants.items()},
            "speech_budget": {
                "initiative_count_10m": self._initiative_count(session),
                "last_iris_activity_at": session.last_iris_activity_at,
                "iris_share_2m": self._iris_speech_share(session),
                "cooldown_active": self._initiative_cooldown_active(session),
                "budget_exceeded": self._speech_budget_exceeded(session),
            },
            "deferred_reactions": [
                self._deferred_view(item) for item in session.deferred_reactions
            ],
            "active_tasks": [
                {
                    "name": task.get_name(),
                    **session.task_details.get(task, {}),
                }
                for task in session.active_tasks
                if not task.done()
            ],
            "last_cancellation": session.last_cancellation,
            "turn_detector": {
                "provider": getattr(self._turn_detector, "name", "heuristic"),
                "ready": bool(self._turn_detector is not None and getattr(self._turn_detector, "ready", False)),
                "fallback": not bool(
                    self._turn_detector is not None and getattr(self._turn_detector, "ready", False)
                ),
                "error": getattr(self._turn_detector, "error", None),
            },
        }

    def _register_task(
        self,
        session: ConversationSession,
        coroutine,
        *,
        name: str,
        generation: int,
        reason: str,
    ) -> asyncio.Task:
        task = asyncio.create_task(coroutine, name=name)
        session.active_tasks.add(task)
        session.task_details[task] = {
            "generation": generation,
            "reason": reason,
        }

        def finished(done: asyncio.Task) -> None:
            session.active_tasks.discard(done)
            session.task_details.pop(done, None)
            if not done.cancelled():
                with contextlib.suppress(Exception):
                    done.exception()

        task.add_done_callback(finished)
        return task

    async def _run_adjudication(self, transcript: str, **kwargs):
        async with self._decision_semaphore:
            return await self._adjudicator.adjudicate(transcript, **kwargs)

    async def _run_deferred(
        self,
        session: ConversationSession,
        reaction: DeferredReaction,
    ) -> None:
        delay = max(0.0, reaction.earliest_at - time.monotonic())
        if delay:
            await asyncio.sleep(delay)
        async with session.lock:
            now = time.monotonic()
            valid = bool(
                reaction in session.deferred_reactions
                and reaction.attempts == 0
                and reaction.generation_created == session.generation
                and now <= reaction.expires_at
                and now - session.last_human_activity_at
                >= reaction.minimum_silence_ms / 1000
                and not self._speech_budget_exceeded(session)
                and not self._initiative_cooldown_active(session)
            )
            if not valid:
                with contextlib.suppress(ValueError):
                    session.deferred_reactions.remove(reaction)
                return
            reaction.attempts += 1
            with contextlib.suppress(ValueError):
                session.deferred_reactions.remove(reaction)
            utterance_id = uuid4().hex
            session.live_utterance_ids.add(utterance_id)
            session.initiative_utterance_ids.add(utterance_id)
            session.utterance_generations[utterance_id] = session.generation
            session.initiative_timestamps.append(now)
            session.phase = ConversationPhase.GENERATING
            sender = session.event_sender
            generation = session.generation
        if sender is not None:
            await sender(
                self._event(
                    session,
                    "conversation.reaction",
                    utterance_id=utterance_id,
                    payload={
                        "deferred_id": reaction.id,
                        "initiative": True,
                        "trigger_message_ids": reaction.trigger_message_ids,
                    },
                )
            )
        if self._deferred_response_handler is None:
            async with session.lock:
                session.phase = ConversationPhase.LISTENING
            return
        try:
            await self._deferred_response_handler(
                session.session_id,
                reaction,
                generation,
                utterance_id,
            )
        except asyncio.CancelledError:
            raise
        except Exception as error:
            async with session.lock:
                if generation == session.generation:
                    session.phase = ConversationPhase.LISTENING
            if self._publish is not None:
                self._publish(
                    "conversation.deferred_failed",
                    "warning",
                    "Deferred reaction could not start",
                    {
                        "session_id": session.session_id,
                        "reaction_id": reaction.id,
                        "error": type(error).__name__,
                    },
                )

    @staticmethod
    def _deferred_view(reaction: DeferredReaction) -> dict[str, object]:
        return {
            "id": reaction.id,
            "trigger_message_ids": reaction.trigger_message_ids,
            "topic_key": reaction.topic_key,
            "earliest_at": reaction.earliest_at,
            "expires_at": reaction.expires_at,
            "minimum_silence_ms": reaction.minimum_silence_ms,
            "required_score": reaction.required_score,
            "generation_created": reaction.generation_created,
            "attempts": reaction.attempts,
        }

    @classmethod
    def _topic_key(cls, text: str) -> str:
        words = [word for word in cls._normalize(text).split() if len(word) > 3]
        return "-".join(words[:4]) or "conversation"

    @staticmethod
    def _initiative_cooldown_active(session: ConversationSession) -> bool:
        now = time.monotonic()
        return bool(
            session.initiative_timestamps
            and now - session.initiative_timestamps[-1] < 90
        ) or (
            session.last_iris_activity_at > 0
            and now - session.last_iris_activity_at < 20
        )

    @classmethod
    def _speech_budget_exceeded(cls, session: ConversationSession) -> bool:
        return cls._initiative_count(session) >= 2 or cls._iris_speech_share(session) > 0.35

    @staticmethod
    def _iris_speech_share(session: ConversationSession) -> float:
        now = time.monotonic()
        spoken = sum(
            item.duration_seconds
            for item in session.spoken_windows
            if item.finished_at >= now - 120
        )
        return min(1.0, spoken / 120.0)

    def _schedule_memory(
        self,
        message: StoredTimelineMessage,
        speaker_role: SpeakerRole,
        speaker_confidence: float,
        stt_uncertain: bool,
        decision_reason: DecisionReason,
    ) -> None:
        if (
            self._memory_service is None
            or speaker_role is not SpeakerRole.PRIMARY
            or speaker_confidence < 0.7
            or stt_uncertain
            or decision_reason in {
                DecisionReason.AMBIENT_SPEECH,
                DecisionReason.SELF_TALK,
                DecisionReason.OTHER_PERSON,
                DecisionReason.INCOMPLETE_TURN,
            }
        ):
            return
        if self._memory_service.uses_background_extraction:
            self._memory_service.extract_high_precision_from_message(message)
        # The durable LLM consolidator must be anchored at the terminal Iris
        # reply, not this user message.  See _commit_assistant.

    def _commit_assistant(
        self,
        session: ConversationSession,
        utterance_id: str,
        content: str,
        generation: int,
        *,
        status: str,
    ) -> None:
        if self._runtime.memory_incognito or not content:
            return
        source = self._store.message_for_utterance(utterance_id)
        assistant, _ = self._store.append_message(
            role="assistant",
            content=content,
            input_mode="voice",
            status=status,
            utterance_id=utterance_id,
            generation=generation,
            turn_id=source.turn_id if source is not None else None,
            reply_to_message_id=source.id if source is not None else None,
            metadata={"playback_acknowledged": True},
        )
        if status == "completed" and self._memory_service is not None:
            self._memory_service.schedule_extraction(assistant)

    def _persist_state(self, session: ConversationSession, appraisal, relationship_delta: dict[str, float]) -> None:
        self._store.save_character_state_snapshot(
            PRIMARY_RELATIONSHIP_ID,
            session.affect.as_dict(),
        )
        participant = session.participants[appraisal.target_participant]
        self._store.upsert_participant_state(
            relationship_id=PRIMARY_RELATIONSHIP_ID,
            participant_key=participant.participant_key,
            role=participant.role,
            facets={
                "familiarity": participant.familiarity,
                "trust": participant.trust,
                "warmth": participant.warmth,
                "tension": participant.tension,
                "playfulness": participant.playfulness,
            },
            evidence_count=participant.evidence_count,
        )
        self._store.append_character_state_event(
            relationship_id=PRIMARY_RELATIONSHIP_ID,
            participant_key=participant.participant_key,
            event_kind=appraisal.event_kind,
            confidence=appraisal.confidence,
            intensity=appraisal.intensity,
            cause_message_ids=appraisal.cause_message_ids,
            delta={
                "emotion_impulses": appraisal.emotion_impulses,
                "relationship": relationship_delta,
            },
        )

    def _restore_state(self, session: ConversationSession) -> None:
        if self._runtime.memory_incognito:
            return
        snapshot = self._store.load_character_state_snapshot(PRIMARY_RELATIONSHIP_ID)
        if snapshot and snapshot.get("schema_version") == 1:
            values = dict(snapshot["state"])
            allowed = AffectState.__dataclass_fields__
            session.affect = AffectState(**{key: value for key, value in values.items() if key in allowed})
            self._reducer.decay(session.affect, recovery=self._runtime.live_conversation_mood_recovery)
        for row in self._store.load_participant_states(PRIMARY_RELATIONSHIP_ID):
            facets = dict(row["facets"])
            session.participants[str(row["participant_key"])] = ParticipantState(
                participant_key=str(row["participant_key"]),
                role=str(row["role"]),
                evidence_count=int(row["evidence_count"]),
                updated_at=str(row["updated_at"]),
                **facets,
            )

    def _is_assistant_echo(self, session: ConversationSession, transcript: str) -> bool:
        if not session.playback_segments:
            return False
        if (
            getattr(self._runtime, "live_conversation_echo_mode", "auto") == "half_duplex"
            and any(segment.finished_at is None for segment in session.playback_segments)
        ):
            return True
        now = time.monotonic()
        normalized = self._normalize(transcript)
        for segment in reversed(session.playback_segments):
            end = segment.finished_at or now
            if now - end > 3.0:
                continue
            candidate = self._normalize(segment.text)
            if candidate and SequenceMatcher(None, normalized, candidate).ratio() >= 0.82:
                return True
        return False

    @staticmethod
    def _normalize(text: str) -> str:
        return re.sub(r"[^\w]+", " ", text.casefold(), flags=re.UNICODE).strip()

    @staticmethod
    def _significance(text: str) -> float:
        lowered = text.casefold()
        strong = ("важно", "обещаю", "извини", "прости", "ненавижу", "люблю", "уволили", "умер")
        if any(item in lowered for item in strong):
            return 0.8
        return min(0.55, 0.15 + len(text) / 500)

    @staticmethod
    def _state_context(session: ConversationSession, decision: ConversationDecision) -> str:
        affect = session.affect
        participant = session.participants.get("primary", ParticipantState())
        prior_reply = session.last_generated_assistant_reply.strip()
        prior_reply_context = (
            f' Последняя фактически сгенерированная реплика Iris: "{prior_reply[:1000]}". '
            "Используй её только для связного продолжения и исправления собственной ошибки."
            if prior_reply
            else ""
        )
        return (
            StateToBehaviorRenderer().render(affect, participant).prompt_block(allowed_action=decision.action.value)
            + prior_reply_context
            + " Не проговаривай служебную рамку."
        )

    @staticmethod
    def _initiative_count(session: ConversationSession) -> int:
        cutoff = time.monotonic() - 600
        return sum(timestamp >= cutoff for timestamp in session.initiative_timestamps)

    @staticmethod
    def _event(
        session: ConversationSession,
        event_type: str,
        *,
        turn_id: str | None = None,
        utterance_id: str | None = None,
        payload: dict[str, object] | None = None,
    ) -> dict[str, object]:
        return {
            "type": event_type,
            "version": 2,
            "session_id": session.session_id,
            "generation": session.generation,
            "turn_id": turn_id or session.active_turn_id or "",
            "utterance_id": utterance_id,
            "created_at": datetime.now(UTC).isoformat(timespec="milliseconds"),
            **(payload or {}),
        }
