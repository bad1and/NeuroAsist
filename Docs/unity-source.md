# Unity source handoff

The V0.4.1 Unity avatar source is currently an unpublished working tree. It is not a Git repository and the proposed `bad1and/NeuroAsistAvatar` remote is not available. This repository must not claim that a clean clone contains, pins, or can build that source.

## Required publication procedure

1. Create or provide the canonical Unity repository URL.
2. Initialize and commit the Unity project after excluding generated Unity folders (`Library`, `Temp`, `Logs`, `Obj`, `Build`, `Builds`, and `UserSettings`).
3. Push the first immutable source commit.
4. Add it here as a Git submodule or record the URL and exact commit in `version-manifest-v0.4.1.json`.
5. Add a build manifest with the standalone executable hash and a compatibility table for Avatar Protocol v1/v2.
6. Run Unity Test Runner and the backend/avatar smoke checklist from a clean clone.

## Frozen compatibility expectations

- Unity Editor: `2022.3.62f3`
- UniVRM: `1.0`
- uLipSync: `3.1.5`
- Animation Rigging: `1.2.1`
- Backend Avatar Protocol: v1 and v2

Until that publication is complete, Unity remains an optional external renderer and backend/web behaviour must stay independent of its presence.
