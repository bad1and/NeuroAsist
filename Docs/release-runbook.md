# Iris 1.0 release runbook

`1.0.0` is a source-tree target, not permission to publish an installer. This
runbook produces a traceable **release candidate**; a human release owner makes
the final publication decision only after every item in the
[release checklist](release-checklist.md) has evidence.

## Automated evidence

The required GitHub checks are intentionally separated by cost and platform:

| Workflow | Trigger | Evidence |
| --- | --- | --- |
| `Documentation` | Pull request, `main` | version mirrors, environment reference and maintained local links |
| `CI` | Pull request, `main` | full backend pytest, web Vitest/build and Windows Rust check |
| `Synthetic lifecycle soak` | weekly and manual dispatch | one-hour cancellation/state/memory report |
| `Build Windows release candidate` | `v*` tag or manual dispatch | NSIS installer, packaged-core smoke, SHA-256 manifest and optional Authenticode status |

The synthetic soak is a lifecycle regression test. It has no microphone, model
download or Unity renderer, so a passing report is not evidence for the real
voice/avatar acceptance gate.

## Candidate build runner

`Build Windows release candidate` runs only on a protected self-hosted runner
labelled `Windows` and `iris-release`. It must have the pinned Unity editor,
Rust, Node and Python available. The runner needs `NEUROASIST_UNITY_EDITOR` set
to the Unity executable because the avatar resource is intentionally not kept
in Git.

Configure the GitHub `release-candidate` environment with the appropriate
review policy. If the installer must be signed, install the signing certificate
in that runner's Windows certificate store and set the environment secret
`WINDOWS_CERTIFICATE_THUMBPRINT`. `WINDOWS_TIMESTAMP_URL` is optional; the
build script uses DigiCert's timestamp service when it is omitted.

The candidate workflow never creates a GitHub Release or declares a build
stable. A tag must exactly equal `v` plus the root `VERSION` value.

The NSIS candidate is a CPU-base installer. A CUDA-enabled PyTorch wheel adds
multiple gigabytes of optional DLLs and exceeds NSIS's 2 GiB packaging limit.
The supported default voice configuration is CPU; a GPU runtime must be shipped
and qualified as a separate, explicit add-on before it can be advertised in a
public installer.

## Candidate contents and attestation

The build produces an ignored `artifacts/` directory with:

- the NSIS installer;
- `iris-<version>-release-manifest.json` containing the installer SHA-256,
  commit, size and signing status.

Before NSIS packages the result, `scripts/check_release_artifact.py` scans the
complete PyInstaller sidecar and Unity resource trees for `.env`, SQLite data,
diagnostic audio and other private runtime paths. NSIS is opaque after packing,
so the manifest records that this is a pre-NSIS resource-tree scan. Keep the
workflow artifact together with the release evidence.

For a local candidate rehearsal after Unity is built:

```powershell
.\scripts\build-desktop-release.ps1 -RequireCleanWorktree -ArtifactDirectory artifacts
```

To sign locally, pass the certificate thumbprint explicitly:

```powershell
.\scripts\build-desktop-release.ps1 -RequireCleanWorktree `
  -SigningCertificateThumbprint '<thumbprint>' -ArtifactDirectory artifacts
```

The script verifies a requested Authenticode signature and smoke-tests the
packaged sidecar with the desktop token enabled. An unsigned candidate remains
an internal candidate.

## Manual release evidence

Attach reports, screenshots or logs to the checklist for these non-CI gates:

1. clean Windows VM install, first run, upgrade and uninstall;
2. backup restore on a clean install and corrupt-database handling;
3. at least one hour of real microphone voice plus both Unity placements,
   including reconnect and barge-in scenarios;
4. approved memory/persona and 30-minute LLM cost evaluations;
5. dependency, model, asset, privacy and security review;
6. release owner approval, published checksum and rollback location.

Do not reuse a checksum after rebuilding. The installer, its manifest, the
commit and the release tag are one evidence set.
