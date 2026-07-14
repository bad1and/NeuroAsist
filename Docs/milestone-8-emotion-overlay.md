# Milestone 8 — Emotion Engine and Avatar Overlay

## Delivered in this repository

- `EmotionEngine` owns one renderer-neutral state for face emotion, body gesture
  arbitration, speech ownership and transition timings.
- A metadata frame is applied once per utterance. Repeated frames are
  idempotent, and a stop for an older utterance cannot reset a newer expression.
- Gesture mappings are validated against the canonical Character Protocol v3
  enum. Invalid/missing mappings fall back to a neutral, safe default and are
  exposed through `GET /avatar/status`.
- The checked-in [mapping asset](../apps/protocol/avatar-emotion-mapping.json)
  contains Unity-ready expression, motion-profile, allowed-gesture and timing
  values for every canonical emotion.

## Renderer handoff still required

The Unity project remains unpublished (see [Unity source handoff](unity-source.md)).
Consequently this repository cannot honestly ship or test the Windows renderer
requirements: transparent D3D11 alpha window, click-through/drag/lock, monitor
and DPI positioning, persisted placement, gaze/idle clips and frame profiling.

When the Unity source is published, its startup sequence must load the mapping
asset, validate expression and clip names, apply the attack/hold/release state,
and persist overlay geometry. It must retain Avatar Protocol v1/v2 fallback
behaviour for existing deployments. The backend state machine is deliberately
independent of that renderer so those changes do not alter conversation or voice
behaviour.
