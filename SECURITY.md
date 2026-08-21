# Security policy

## Supported code line

Security fixes target the current Iris 1.x source line. Historical documents,
fixtures and archived blueprints are not supported runtimes.

The public installer is not considered released until the
[release checklist](Docs/release-checklist.md) is approved. Development builds
must not be represented as hardened multi-user or network services.

## Reporting

Report vulnerabilities privately to the repository owner through GitHub's
private vulnerability reporting when enabled. If that channel is unavailable,
open a minimal issue asking for a private contact method; do not include API
keys, user databases, prompts, personal audio or a working exploit in public.

Include:

- affected commit/version and Windows version;
- component and prerequisite configuration;
- impact and reproducible steps with synthetic data;
- whether desktop token, filesystem access or Coding Agent is involved;
- suggested mitigation if known.

## Security boundaries

- Desktop core binds to loopback and requires an ephemeral token for HTTP/WS.
- API keys belong in Credential Manager or an untracked `.env`.
- STT/TTS are local by default, while LLM requests leave the machine.
- SQLite/user files are single-user local data, not a multi-tenant boundary.
- Coding Agent must remain Docker-only with no network, no live project mount,
  dropped capabilities and no host-shell fallback.
- Unity is a supervised local child process and receives only the loopback URL,
  ephemeral token and avatar commands required for its session.

Do not weaken these boundaries to make a failed optional component appear
available. Fail closed and surface a diagnostic instead.

## Secrets and private artifacts

Never commit `.env`, Credential Manager exports, real conversation databases,
raw diagnostic microphone audio, proprietary voice references, signing keys or
release certificates. Before publishing an artifact, complete the privacy,
secret and license checks in the release checklist.
