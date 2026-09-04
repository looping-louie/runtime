# Looping Louie Runtime

The runtime is the worker process that claims queued Pipeline runs from the
Looping Louie API and executes them in configured local Git checkouts.

## Configuration

Each worker maps API projects to local repository checkouts. This keeps a
worker from executing a task in an arbitrary directory supplied by an API run.
The top-level `user_id` is propagated as `X-User-ID` on every API request.
On the first normal start, each project without a `worker_id` is provisioned
through `POST /api/v1/workers`; the API-generated ID is written back to this
file immediately and reused on later starts.

```json
{
	"api_base_url": "http://127.0.0.1:8000/api/v1",
	"user_id": "local-user",
	"poll_interval_seconds": 2,
	"projects": [
		{
			"project_id": "local-project",
			"repository_path": "/absolute/path/to/checkout"
		}
	]
}
```

Validate configuration, Git checkout ownership, and a clean worktree before
starting a worker:

```sh
looping-louie-runtime --config runtime.json --check
```

Start the worker from a normal terminal:

```sh
looping-louie-runtime --config runtime.json
```

During initial provisioning, the runtime always advertises `louie`. It also
advertises `codex_cli` only when the configured `LOUIE_CODEX_COMMAND` passes
both `--version` and `login status`. The same detection is refreshed while the
worker runs and the current Harness set is sent with each project heartbeat.
Installing Codex, logging in, or logging out therefore updates claim admission
without replacing the persisted `worker_id`; detection is cached for 30
seconds. It advertises `copilot_cli` when `LOUIE_COPILOT_COMMAND` (defaulting
to `copilot`) passes `--version`; Copilot authentication is verified when the
CLI executes the selected turn.

The worker polls every configured project, claims at most one available run
per project in each cycle, and waits for `poll_interval_seconds` before the
next cycle. A failed project claim or execution is logged without skipping
other configured projects, then retried in the next cycle. Unexpected runtime
defects stop the worker instead of retrying indefinitely.

## Execution

For each Activity child scheduled within a claimed Pipeline run, the runtime
performs these checkpoint actions in the mapped checkout:

- `collect_snapshot`: sends bounded repository context, project metadata, and
	the checkout constitution to the API.
- `apply_operations`: validates and atomically applies API-provided file
	operations without permitting checkout escape or symbolic-link traversal.
- `run_harness`: runs one API-selected `codex_cli` or `copilot_cli` v1 agent
	turn through the corresponding local CLI. Both inject the frozen Persona,
	pass the API-frozen model, forbid direct Git commits, and report the final
	phase, agent, iteration, structured output, response, timestamps and duration,
	models, proposed commit message, process exit, versioned Skills, source and
	final Git commits, diff, changed files, usage, diagnostics, and session
	reference to the API. Codex materializes Skills at
	`.agents/skills/<name>/SKILL.md`; Copilot materializes them at
	`.github/skills/<name>/SKILL.md`. Temporary Skill directories are removed
	before the checkout diff is collected.
- `submit_review_input`: sends the final Git diff and bounded changed-file
	contents.
- `commit_if_allowed`: enforces local `louie.yaml` Git policy, then commits an
	API-approved change when allowed. The runtime captures the policy before
	planned operations begin, so an operation cannot change the policy that
	authorizes its own commit.

After a child reaches a terminal state, the runtime advances the Pipeline and
executes its next scheduled child in the same checkout until the Pipeline is
terminal. It renews the active Pipeline lease before each checkpoint result and
before scheduling the next child; a rejected renewal stops execution for that
claim. While a blocking `codex_cli` turn is running, a background keepalive
renews the one-minute lease every 30 seconds. A rejected keepalive prevents the
runtime from submitting that local result. Each checkpoint result also includes
the claimed Pipeline run and lease token, so the API rejects stale workers
inside the checkpoint transition.
Malformed Activity responses stop execution for the affected project before
the runtime can advance Pipeline scheduling. Malformed Pipeline claim or
scheduler responses stop execution before the runtime can checkpoint a child or
silently treat a Pipeline as complete.

The runtime never selects a checkout from an API response. It uses only the
project-to-checkout mapping in its local configuration. Repository context
collection is read-only and does not stage untracked files or otherwise modify
the Git index.

For `codex_cli` and `copilot_cli`, the model is selected by the API and supplied as
`requested_model`; the runtime refuses to use a local model default and passes
the value to the CLI `--model` option. It reads machine-owned environment
settings: `LOUIE_CODEX_COMMAND` defaults to `codex`,
`LOUIE_CODEX_SANDBOX` defaults to `workspace-write`,
`LOUIE_CODEX_TIMEOUT_SECONDS` defaults to `1800` seconds,
`LOUIE_COPILOT_COMMAND` defaults to `copilot`, and
`LOUIE_COPILOT_TIMEOUT_SECONDS` defaults to `1800` seconds. Persona and Skill
content comes only from the immutable Activity snapshot supplied by the API;
the runtime does not fetch mutable instruction resources during execution.
Codex/OpenAI authentication remains local to the CLI and does not use API
Linked Services. The public JSONL stream supplies the session reference, token
usage, response, and diagnostics. After the process exits, the runtime reads
that session's local `turn_context` to observe the effective model and reasoning
effort. If session metadata is unavailable, `actual_model` falls back to the
explicit CLI model and `reasoning_effort` remains `null`. Non-zero exits and
timeouts retain all JSONL observations emitted before failure.
Every submitted turn identifies the normalized contract as `schema_version=v1`
and reports the frozen `codex_cli` Harness identity. The API validates that
identity and publishes the common Harness observation envelope; Codex-specific
session and materialized-Skill fields remain adapter details.
For commit-enabled runs, Codex must return a structured final response with a
non-empty `commit_message`. The runtime submits that proposal to the API and
performs Git only if the next checkpoint is `commit_if_allowed`.
