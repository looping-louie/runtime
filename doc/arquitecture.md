# Looping Louie Runtime Architecture

This document describes the software architecture of the Looping Louie Runtime.
The temporary cross-repository product architecture is documented in
[`ll-architecture.md`](ll-architecture.md). It defines the shared API/runtime
ownership boundaries, Worker provisioning, Harness model, and execution flow.

Looping Louie Runtime is a local worker for Pipeline execution. It executes
API-directed local checkpoints in configured Git checkouts and returns their
results to the API.

## Source Structure

Runtime source modules are grouped by ownership. Composition, polling, and
checkpoint orchestration remain directly under `src`, while HTTP adapters and
local Git operations have dedicated packages.

```text
src/
|-- main.py                Builds configured clients, worker, and polling loop
|-- configuration/         Parses configuration and persists provisioned IDs
|-- provisioning.py        Creates missing workers and persists their IDs
|-- polling/               Polls project queues with operational retry
|-- clients/
|   |-- pipeline_client.py
|   |                       Claims, renews, and advances Pipeline runs over HTTP
|   `-- activity_client.py Reads and checkpoints Activity runs over HTTP
|-- executor.py            Coordinates local checkpoint execution for a claim
|-- harnesses/
|   |-- capabilities.py    Detects executable and authenticated Harnesses
|   |-- cli_common.py      Defines shared CLI turn and result-contract helpers
|   |-- executor.py        Routes frozen Harnesses to local adapters
|   |-- instructions.py    Validates and materializes shared instruction snapshots
|   |-- codex_cli/         Runs Codex, materializes instructions, and captures
|   |                      JSONL plus local-session observations
|   `-- copilot_cli/       Runs Copilot, materializes instructions, and captures
|                          JSONL observations
|-- services/
|   `-- git/
|       |-- repository_context.py  Inspects Git state and builds bounded context
|       |-- file_operations.py     Validates and atomically applies planned writes
|       `-- policy.py              Parses and evaluates local Git commit policy
`-- doc/arquitecture.md    Documents runtime ownership and execution boundaries
```

Tests follow the same ownership boundaries. Cross-boundary orchestration tests
remain directly under `tests`.

```text
tests/
|-- clients/
|   |-- test_pipeline_client.py
|   `-- test_activity_client.py
|-- services/
|   `-- git/
|       `-- test_repository_context.py
|-- test_config.py
|-- test_executor.py
|-- test_runner.py
`-- test_worker.py
```

### Composition

`main.py` is the composition root. It loads and validates `RuntimeConfig`,
constructs the cached local-Harness detector, provisions missing workers,
creates the HTTP clients, passes them to `ActivityExecutor`, and constructs
`RuntimeWorker` with the executor callback and capability supplier. It then
invokes `run_forever`.

Dependency flow is:

```text
main -> configuration, capabilities, provisioning, clients, executor, polling
worker -> ClaimClient, executor callback
executor -> activity client, pipeline client, services.git
clients -> HTTP API
services.git -> configured Git checkout
```

The worker and executor depend on protocols rather than concrete HTTP clients.
Tests use those protocols to isolate polling and checkpoint behavior from HTTP.

## Checkpoint Execution

`ActivityExecutor` processes the API-selected child until its Activity status
is terminal. It supports these local actions:

### `collect_snapshot`

Build repository context, project profile, and constitution. Return snapshot
data and the source commit SHA to the API.

### `apply_operations`

Validate and apply planned create, replace, replace-text, and delete
operations. Return the application outcome, diff, and changed files.

### `run_harness`

Validate the API-frozen `codex_cli` or `copilot_cli` Harness and the pending
turn's requested model and instruction snapshot. Pass the model to the selected
CLI, inject the Persona content into the task prompt, and materialize each Skill
for the duration of the process. Codex uses
`.agents/skills/<normalized-name>/SKILL.md`; Copilot uses
`.github/skills/<normalized-name>/SKILL.md`.
Each selected Skill is referenced explicitly in the prompt by its normalized
`$name`. Temporary Skill directories are removed before diff collection and
are also removed when the process fails. A checkout-owned directory with the
same Skill name is never overwritten. The prompt forbids Codex from creating a
Git commit. Writer and aggregator turns require a machine-readable final summary
plus a commit proposal for commit-enabled runs; proposal and review turns use
read-only sandboxing and return structured output. That output and the turn
identity, role, phase, and iteration are submitted through `run_harness`; Git
is executed only after the API returns `commit_if_allowed`. Successful results
and failures report timestamps, duration, requested and actual model, reasoning
effort, session reference, all token counters, exit code, diagnostics,
materialized Skill versions, source and final Git SHAs, diff, changed files,
and any final response. The public JSONL stream supplies partial turn data; the
runtime supplements it with effective model and effort from the matching local
Codex session `turn_context`. If that metadata is absent, the requested model is
reported as actual and effort remains unknown. CLI authentication remains local
and API Linked Services are not used by either Harness.

The checkpoint result also carries `schema_version=v1` and the frozen Harness
identity. These discriminate the common observation envelope without moving
adapter-specific parsing, session lookup, or Skill materialization out of its
adapter. The API validates and durably normalizes the submitted observation.

### `submit_review_input`

Read the final diff and bounded changed-file contents. Return the review input.

### `commit_if_allowed`

Apply the pre-execution local policy and commit eligible changes. Return the
commit outcome, SHA, or denial reason.

The executor validates Activity and Pipeline response fields that control local
progress. Malformed responses stop the affected project rather than causing
an implicit checkpoint or Pipeline completion.

## Local State and Git Boundaries

The runtime stores no run state locally. It persists only API-generated worker
IDs in its configuration after initial provisioning. API Pipeline and Activity
runs remain the source of truth for progress, retry tokens, and scheduling.

The configured checkout is the local side-effect boundary. Before the worker
starts, every checkout must be a clean Git repository. During execution:

- Repository context reads do not stage untracked files or modify the Git index.
**File operations.** Operations reject traversal, symbolic links, invalid
paths, and invalid operation shapes before writing files.

**Commit policy.** Local `louie.yaml` policy is loaded before planned
operations begin. That captured policy governs all commit checkpoints for the
claimed Pipeline run.

**Commit decision.** `commit_if_allowed` does not commit when policy, branch
protection, commit metadata, or repository state blocks the action.

## Lease and Failure Boundaries

A successful claim includes a secret lease token. The executor renews that
lease before every Activity checkpoint and before Pipeline continuation. It
also submits the Pipeline run ID and lease token with every Activity checkpoint.
During a blocking `codex_cli` turn, a background keepalive renews the lease
every 30 seconds. If renewal fails, the completed local turn is not submitted.

The API validates lease ownership before generation and again atomically when
it persists an Activity or Pipeline transition. A runtime whose lease has
expired, or whose claim has been replaced, cannot advance durable state.

Operational HTTP, Git, validation, and checkpoint failures are normalized as
`RuntimeError`. The worker records the project failure and continues polling
other configured projects. The long-running runner retries another cycle
after `poll_interval_seconds`.

## Architectural Inspection Points

Future architecture reviews can use these boundaries to locate responsibility
drift:

**Composition.** `main.py` remains wiring only; it does not acquire execution
rules.

**Polling.** `worker.py` remains responsible for project polling and error
isolation, not checkpoint behavior.

**Checkpoint orchestration.** `executor.py` remains the orchestration point for
the local half of the checkpoint protocol.

**Local Git services.** The `services.git` package owns repository context,
file operations, and commit policy without HTTP or scheduling concerns.

**HTTP clients.** The `clients` package contains transport adapters and does
not perform filesystem or Git operations.

**New actions.** New Activity action types require an explicit executor action
handler and a corresponding API checkpoint contract.

**Persistence.** New local persistence requires an ownership decision because
the API is currently the sole durable execution-state authority.
