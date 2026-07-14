# V0.5 Milestone 2 — Episode Manager

Milestone 2 groups the one canonical timeline into internal conversation episodes. Episodes are implementation structure for continuity and Journal readability; they are not user-created chats and do not alter the companion identity.

## Lifecycle

Migration `2` adds `conversation_episodes` and links every `conversation_messages` row through `episode_id`.

- A new active episode is created only when a real message is appended.
- Consecutive messages remain in the active episode after a short pause.
- A hard inactivity gap closes it with `inactivity`; a new calendar day after the soft gap closes it with `calendar_boundary`.
- Message-count or estimated-token pressure closes it with `context_pressure` before the next message begins a new one.
- A graceful manual close uses `manual_reset`.
- Startup recovery keeps a fresh active episode, but closes a stale one with `application_restart`; it never creates an empty episode.
- The V0.4.1 imported timeline becomes one closed migration episode with `recovery` provenance.

The baseline intentionally has no LLM topic classifier. Semantic topic shift, rolling/final summaries, and Context Manager remain deferred to Milestones 3 and later.

## Configuration

The startup policy is environment-configured and exposed in public settings for diagnostics:

```env
EPISODES_ENABLED=true
EPISODE_SOFT_INACTIVITY_MINUTES=20
EPISODE_HARD_INACTIVITY_MINUTES=60
EPISODE_MAXIMUM_MESSAGES=120
EPISODE_MAXIMUM_ESTIMATED_TOKENS=16000
```

`EPISODES_ENABLED=false` keeps Timeline V2 available but leaves new rows without episodes, providing a bounded rollback switch during investigation.

## API and UI

- `GET /episodes` and `GET /episodes/{id}` expose internal lifecycle diagnostics.
- `POST /episodes/current/close` closes the active episode only when it already contains messages.
- `DELETE /episodes/{id}` removes an explicitly selected period and its messages.
- `GET /timeline/journal` now returns episode groups. The Journal UI renders those groups by date, status, and boundary reason; it does not expose chat switching or manual episode creation.
- `episode.started`, `episode.closed`, recovery, manual-close, and deletion events are sent through the existing runtime event bus.

## Verification

`tests/test_episode_manager.py` covers inactivity, calendar boundary, pressure segmentation, no-empty guarantees, manual close, and restart recovery. `tests/test_timeline_v2.py` verifies the V0.4.1 fixture now applies migrations `1` and `2` and is represented by one imported episode.
