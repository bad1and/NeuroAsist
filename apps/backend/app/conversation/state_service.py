"""One canonical state pipeline shared by text, ordinary voice and live voice."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
from threading import RLock

from apps.backend.app.conversation.behavior import BehaviorGuide, StateToBehaviorRenderer
from apps.backend.app.conversation.decision import ConversationDecisionEngine
from apps.backend.app.conversation.relationship import RelationshipProfile, RelationshipProfileBuilder
from apps.backend.app.conversation.reflection import ReflectionService
from apps.backend.app.conversation.schemas import EventAppraisal, SpeakerRole
from apps.backend.app.conversation.state import AffectState, CharacterStateReducer, ParticipantState
from apps.backend.app.llm.base import LLMProvider
from apps.backend.app.storage.timeline import PRIMARY_RELATIONSHIP_ID, TimelineStore


@dataclass(frozen=True)
class StateTurnContext:
    appraisal: EventAppraisal
    affect: AffectState
    relationship: ParticipantState
    profile: RelationshipProfile
    behavior: BehaviorGuide
    state_applied: bool
    event_id: str | None

    def prompt_block(self, *, allowed_action: str = "respond") -> str:
        return self.behavior.prompt_block(allowed_action=allowed_action)


class CharacterStateService:
    """Synchronous, bounded work; it does not add a network call before a reply."""

    def __init__(
        self,
        store: TimelineStore,
        *,
        recovery: str = "natural",
        reflection_policy=None,
        event_publisher=None,
        reflection_llm_provider: LLMProvider | None = None,
    ) -> None:
        self._store = store
        self._recovery = recovery
        self._reducer = CharacterStateReducer()
        self._renderer = StateToBehaviorRenderer()
        self._profiles = RelationshipProfileBuilder()
        self._reflections = ReflectionService(store, reflection_llm_provider, event_publisher)
        self._reflection_policy = reflection_policy or (lambda: (True, .55))
        self._publish = event_publisher
        self._decision = ConversationDecisionEngine()
        self._lock = RLock()
        # App construction precedes lifespan startup, so SQLite may not exist
        # yet. Restore lazily on the first actual turn after init_db().
        self._affect, self._participants = AffectState(), {"primary": ParticipantState()}
        self._loaded = False

    def current(self, participant_key: str = "primary") -> StateTurnContext:
        with self._lock:
            self._ensure_loaded()
            self._reducer.decay(self._affect, recovery=self._recovery)
            participant = self._participants.setdefault(participant_key, ParticipantState(participant_key=participant_key))
            return self._context(EventAppraisal(), participant, False, None)

    def reset(self, scope: str, participant_key: str = "primary") -> StateTurnContext:
        """Scoped reset: mood and relationship are intentionally independent."""
        with self._lock:
            self._ensure_loaded()
            participant = self._participants.setdefault(participant_key, ParticipantState(participant_key=participant_key))
            if scope == "mood":
                epoch = self._affect.mood_epoch + 1
                self._affect = AffectState(mood_epoch=epoch)
                self._store.save_character_state_snapshot(PRIMARY_RELATIONSHIP_ID, self._affect.as_dict(), schema_version=2)
            elif scope == "relationship":
                epoch = participant.relationship_epoch + 1
                participant = ParticipantState(participant_key=participant_key, role=participant.role, relationship_epoch=epoch)
                self._participants[participant_key] = participant
                self._store.upsert_participant_state(relationship_id=PRIMARY_RELATIONSHIP_ID, participant_key=participant_key, role=participant.role, facets={key: getattr(participant, key) for key in ("familiarity", "trust", "warmth", "tension", "playfulness")}, evidence_count=participant.evidence_count)
            else:
                raise ValueError("Unsupported state reset scope")
            self._emit(f"character.state.{scope}_reset", "warning", {"participant_key": participant_key})
            return self._context(EventAppraisal(), participant, False, None)

    async def run_reflection_once(self) -> bool:
        worked = await self._reflections.run_once()
        if worked:
            self._emit("character.reflection.completed", "info", {"worker": "durable"})
        return worked

    def prepare(
        self,
        *,
        transcript: str,
        message_id: str,
        participant_key: str = "primary",
        speaker_role: SpeakerRole = SpeakerRole.PRIMARY,
        speaker_confidence: float = 1.0,
        addressedness: float = 1.0,
        stt_uncertain: bool = False,
        serious: bool = False,
        task_like: bool = False,
    ) -> StateTurnContext:
        """Classify, reduce and durably store exactly once per accepted user message."""
        causal_window = self._store.memory_extraction_context(message_id, 4)
        previous_assistant = next(
            (item.effective_content for item in reversed(causal_window[:-1]) if item.role == "assistant"),
            None,
        )
        appraisal = self._decision.appraise(
            transcript, message_id, participant_key, previous_assistant,
        ).model_copy(
            update={"addressedness": addressedness, "stt_uncertain": stt_uncertain, "serious": serious}
        )
        can_apply = (
            speaker_role is SpeakerRole.PRIMARY
            and speaker_confidence >= .70
            and addressedness >= .48
            and not stt_uncertain
            and appraisal.direction != "external"
        )
        with self._lock:
            self._ensure_loaded()
            participant = self._participants.setdefault(participant_key, ParticipantState(participant_key=participant_key, role=speaker_role.value))
            if not can_apply:
                self._emit("character.state.transition_skipped", "info", {"reason": "speaker_or_uncertainty", "event_kind": appraisal.event_kind})
                return self._context(appraisal, participant, False, None, task_like=task_like)
            idempotency_key = f"state-v2:{message_id}"
            existing_event_id = self._store.character_state_event_for_key(idempotency_key)
            if existing_event_id is not None:
                return self._context(appraisal, participant, False, existing_event_id, task_like=task_like)
            self._reducer.decay(self._affect, recovery=self._recovery)
            self._reducer.apply_affect(self._affect, appraisal)
            today = datetime.now(UTC).date().isoformat()
            used = self._store.load_character_relationship_budget(PRIMARY_RELATIONSHIP_ID, participant_key, today)
            participant, relationship_delta = self._reducer.apply_relationship(
                participant, appraisal, serious=serious, daily_delta_used=used,
            )
            self._participants[participant_key] = participant
            event_id = self._store.apply_character_state_transition(
                relationship_id=PRIMARY_RELATIONSHIP_ID,
                participant_key=participant_key,
                role=participant.role,
                state=self._affect.as_dict(),
                facets={key: getattr(participant, key) for key in ("familiarity", "trust", "warmth", "tension", "playfulness")},
                evidence_count=participant.evidence_count,
                appraisal=appraisal.model_dump(mode="json"),
                relationship_delta=relationship_delta,
                causes=self._affect.causes,
                daily_deltas={key: used.get(key, 0.0) + abs(delta) for key, delta in relationship_delta.items()},
                idempotency_key=idempotency_key,
            )
            # This policy is local and bounded; it adds no network/LLM call and
            # never feeds reflection text into factual retrieval.
            enabled, minimum_significance = self._reflection_policy()
            reflection_queued = self._reflections.schedule(appraisal, event_id, enabled=enabled, minimum_significance=minimum_significance)
            self._emit("character.state.transition_applied", "info", {"event_id": event_id, "event_kind": appraisal.event_kind, "active_causes": len(self._affect.causes)})
            if reflection_queued:
                self._emit("character.reflection.queued", "info", {"event_id": event_id, "event_kind": appraisal.event_kind})
            return self._context(appraisal, participant, True, event_id, task_like=task_like)

    def _context(self, appraisal: EventAppraisal, participant: ParticipantState, applied: bool, event_id: str | None, *, task_like: bool = False) -> StateTurnContext:
        affect_snapshot = deepcopy(self._affect)
        participant_snapshot = deepcopy(participant)
        profile = self._profiles.build(participant_snapshot, affect_snapshot)
        return StateTurnContext(appraisal, affect_snapshot, participant_snapshot, profile, self._renderer.render(affect_snapshot, participant_snapshot, task_like=task_like), applied, event_id)

    def _restore(self) -> tuple[AffectState, dict[str, ParticipantState]]:
        snapshot = self._store.load_character_state_snapshot(PRIMARY_RELATIONSHIP_ID)
        affect = AffectState()
        if snapshot is not None:
            allowed = AffectState.__dataclass_fields__
            affect = AffectState(**{key: value for key, value in dict(snapshot["state"]).items() if key in allowed})
            self._reducer.decay(affect, recovery=self._recovery)
        participants: dict[str, ParticipantState] = {}
        for row in self._store.load_participant_states(PRIMARY_RELATIONSHIP_ID):
            facets = dict(row["facets"])
            participants[str(row["participant_key"])] = ParticipantState(
                participant_key=str(row["participant_key"]), role=str(row["role"]), evidence_count=int(row["evidence_count"]),
                updated_at=str(row["updated_at"]), **{key: value for key, value in facets.items() if key in ParticipantState.__dataclass_fields__},
            )
        return affect, participants or {"primary": ParticipantState()}

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        self._affect, self._participants = self._restore()
        self._loaded = True

    def _emit(self, event_type: str, level: str, metadata: dict[str, object]) -> None:
        if self._publish is not None:
            self._publish(event_type, level, event_type.replace(".", " "), metadata)
