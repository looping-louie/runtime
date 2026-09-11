# Execution Lifecycle

Looping Louie executes Pipeline work through three cooperating components:

- The CLI creates and inspects API resources.
- The API owns all durable Pipeline and Activity state.
- The runtime polls for API-assigned work and performs local checkout actions.

The runtime never mutates durable run status directly. It submits checkpoint
outcomes under an active lease. The API validates those outcomes and persists
the resulting Activity and Pipeline transitions.

## Ownership

### CLI

The CLI is an API client. It creates Pipeline runs and provides operators with
resource-management commands. It does not execute Pipeline steps or select a
local checkout.

### API

The API is the control plane and source of truth for:

- Pipeline definitions, Activity definitions, and their immutable run snapshots.
- Effective model and instruction selection frozen per agent in each CLI Harness
  Activity-run snapshot.
- Pipeline-run, step, and Activity-run status.
- Queue ordering, claim leases, continuation tokens, and idempotency records.
- Shared direct, refinement, and roundtable turn scheduling and planned file
  operations.
- Terminal failure reasons.

Only the API persists a transition such as `queued -> claimed`,
`in_progress -> completed`, or `claimed -> failed`.

### Runtime

The runtime is the local execution plane. It maps an API project identifier
to a configured clean Git checkout, then performs the API-directed checkpoint
actions in that checkout. Its responsibilities are:

- Polling configured projects and claiming at most one run per project.
- Propagating the configured User identity in all API communication.
- Provisioning each missing worker once with locally detected Harnesses.
- Re-detecting local Harness health and reporting the current set on heartbeat.
- Renewing the active Pipeline lease before every state-changing checkpoint.
- Collecting bounded repository context.
- Applying validated planned file operations.
- Supplying review input from the final local diff.
- Evaluating local Git policy and committing allowed changes.
- Reporting the outcome of each local checkpoint to the API.
- Passing the API-frozen CLI Harness model to the local CLI and reporting the
  requested and actual model observations.
- Executing the selected writer, proposal, review, or aggregator turn without
  owning the loop's state machine.
- Identifying each Harness observation with its schema version and frozen
  Harness implementation.
- Preserving CLI Harness timestamps, duration, session, token usage, exit
  status, diagnostics, versioned Skills, Git state, diff, files, and final
  response even when the local process fails.

The runtime must never choose a checkout from an API response or update a
Pipeline or Activity status in local storage.

## Worker Provisioning And Polling

For a project mapping without `worker_id`, the runtime checks the configured
Codex executable and local login, and checks the configured Copilot executable
with `--version`. It always supports `louie`; it adds `codex_cli` only when both
Codex checks succeed and adds `copilot_cli` when the Copilot check succeeds. The project is then registered
through `POST /workers`, and the returned ID is persisted immediately in the
runtime JSON. Later starts reuse that ID and follow the existing heartbeat and
polling flow. During polling, a shared detector refreshes at most every 30
seconds and each project heartbeat replaces the API's observed Harness set.
Consequently a queued Codex run becomes claimable after a successful local
login without reprovisioning the worker or recreating the run. The runtime does
not enumerate CLI models; the API freezes the requested model and the CLI is the
execution-time authority for whether that authenticated account accepts it. All API requests carry the configured `X-User-ID` and the project-specific
`X-Project-ID`.

## Runtime execution lifecycle

### 1. Claim runtime-executable work

The runtime polls each configured Project and claims one compatible Pipeline run
at a time. The API returns the current Activity child and a lease token. The
runtime renews that lease before state-changing checkpoints and Pipeline
continuation; a rejected renewal stops work for that claim.

Human `approval` and `quiz` Activities do not have a runtime execution path.
They wait for a person to submit a decision through the API.

### 2. Collect context and dispatch the selected Harness

For a `louie` Activity, the runtime sends bounded repository context through
`collect_snapshot`. It then handles the API-directed `apply_operations`,
`submit_review_input`, and `commit_if_allowed` checkpoints. File operations are
validated and applied atomically without allowing checkout escape or symbolic
link traversal. Repository context collection is read-only and does not stage
untracked files or otherwise modify the Git index.

For a `codex_cli` or `copilot_cli` Activity, the runtime handles each
`run_harness` checkpoint by invoking the selected local CLI. It passes the
API-frozen `requested_model` rather than a local default and constructs the
turn prompt from the immutable instruction snapshot. Codex materializes Skills
at `.agents/skills/<name>/SKILL.md`; Copilot materializes them at
`.github/skills/<name>/SKILL.md`. Temporary Skill directories are removed before
the checkout diff is collected.

The runtime reads machine-owned settings: `LOUIE_CODEX_COMMAND` defaults to
`codex`, `LOUIE_CODEX_SANDBOX` to `workspace-write`,
`LOUIE_CODEX_TIMEOUT_SECONDS` to `1800`, `LOUIE_COPILOT_COMMAND` to `copilot`,
and `LOUIE_COPILOT_TIMEOUT_SECONDS` to `1800`. Codex authentication remains
local to the worker and does not use API Linked Services.

### 3. Report outcomes and continue the Pipeline

Every checkpoint result carries the Pipeline run and lease token. The API
validates the checkpoint and returns the next requested action or a terminal
Activity result. A blocking CLI Harness turn runs with a background keepalive
that renews the lease every 30 seconds; a rejected keepalive prevents the local
result from being submitted.

CLI Harness results use `schema_version=v1` and the frozen Harness identity.
They include process, timing, model, Git, response, diagnostics, and session
observations. Codex reads local `turn_context` after a process exits to observe
the effective model and reasoning effort; when that information is unavailable,
it falls back to the explicitly requested model. Non-zero exits and timeouts
retain emitted observations.

After an Activity reaches a terminal outcome, the runtime asks the API to
continue the Pipeline. The API schedules the next dependency-ready Activity or
makes the Pipeline run terminal. The runtime uses only its local
Project-to-checkout mapping; it never accepts a checkout path from an API
response.

### 4. Report represented local failures

Some local failures have an existing checkpoint outcome and can be reported to
the API. For example, unsafe planned file operations result in
`apply_operations` with `applied: false`, and denied, empty, or failed commits
result in `commit_if_allowed` with `committed: false`. When the API receives and
accepts one of these outcomes, it persists the resulting terminal transition.

Malformed claims, Activity responses, or scheduler responses stop execution for
the affected Project before the runtime can advance the Pipeline. They are local
operational failures, not direct runtime status updates.
