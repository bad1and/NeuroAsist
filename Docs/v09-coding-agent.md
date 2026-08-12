# V0.9 Coding Agent

Coding Agent is a separately managed, review-first worker. Iris remains the
conversation orchestrator: it detects an explicit coding request, creates a
durable task, sends a short status back to the user, and can deliver a later
instruction or cancellation. The Coding Agent itself never receives live
project access.

## Safety model

1. A task without context files starts in a new, empty task directory. Its
   created files remain there; it never reads or alters a project folder.
2. The optional project-context mode accepts only a server-configured project
   root and copies explicitly requested allowed source files into the task.
   Git metadata, environments, dependencies, database files, logs, secret-like
   files and unsupported extensions are excluded.
3. The model can use a small JSON tool protocol: read/list/write/delete within
   that copy and a policy-checked argv command.
4. Commands run with Docker only: no network, dropped capabilities,
   `no-new-privileges`, read-only container root, non-root user, CPU/memory/PID
   limits, timeout and output caps. Generated commands never execute through a
   host shell.
5. The UI displays task events, command output, errors, tests, changed files
   and unified diff. In standalone mode, confirming the result keeps generated
   files in its workspace; optional project-context tasks have a separate
   `Apply changes` action.
6. Before apply, source hashes are compared with the snapshot. A conflict
   blocks application. Changed originals are copied to the task's
   `apply-backup` folder before any write.

Docker is a hard requirement for execution. If the CLI/daemon/image is absent,
the task fails safely and the UI reports the reason; the backend never falls
back to host command execution.

## One-time host setup

From the repository root, build the locked runtime image:

```powershell
docker build -t neuroasist-coding -f apps/backend/docker/coding.Dockerfile .
```

Ensure Docker Desktop is running, then enable **Coding Agent** in the new left
navigation section. A new task is standalone by default. Add project context
only when the task must edit known source files.

## Configuration

`CODING_WORKSPACE_ROOT` optionally selects where task folders are created; it
must be outside every directory listed in `CODING_ALLOWED_PROJECT_ROOTS`. When
omitted, the workspace is created as `CodingAgentWorkspace` beside the project
root: for example, `B:\\NeuroAsist` uses `B:\\CodingAgentWorkspace`, while a
checkout on another drive uses that checkout's parent directory automatically.
`CODING_ALLOWED_PROJECT_ROOTS` is an optional comma-separated allowlist of
project-context directories. When omitted, the current NeuroAsist repository
root is the only allowed project context.
`CODING_API_KEY` is optional and lets an operator use a dedicated DeepSeek key;
otherwise the normal desktop-provided `DEEPSEEK_API_KEY` is used. The runtime
stores no API key. `CODING_AGENT_ENABLED=false` hides execution globally while
preserving past task records.

See `.env.example` for limits and the Docker image name. Static limits are
operator configuration; workspace/model/enable/auto-delegation are the only
user-facing runtime preferences.

The defaults admit 10,000 approved files and 128 MB per task snapshot. If an
explicitly allowlisted project exceeds that profile, the error identifies
whether the file-count or byte limit was reached. Raise these static limits
only after confirming the project root contains no material you do not want
the Coding Agent model to read.
