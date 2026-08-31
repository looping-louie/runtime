# Looping Louie Runtime

The runtime is the worker process that claims queued Pipeline runs from the
Looping Louie API and executes them in configured local Git checkouts.

## Configuration

Each worker maps API projects to local repository checkouts. This keeps a
worker from executing a task in an arbitrary directory supplied by an API run.
Provision one worker through `POST /api/v1/workers` for each project, then
place the returned ID in that project mapping.

```json
{
	"api_base_url": "http://127.0.0.1:8000/api/v1",
	"poll_interval_seconds": 2,
	"projects": [
		{
			"project_id": "local-project",
			"worker_id": "api-provisioned-worker-id",
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
- `run_harness`: runs one frozen `codex_cli` v1 direct-loop turn through the
  local Codex CLI. It injects the frozen Persona into the prompt, temporarily
  materializes every frozen Skill as `.agents/skills/<name>/SKILL.md`, and
  passes the API-frozen model through `codex exec --model`. It reports the final
  response, requested and actual model, proposed commit message, diff, changed
  files, usage, diagnostics, and session reference to the API. Codex is explicitly
  instructed to leave changes uncommitted. The temporary Skill directories are
  removed before the checkout diff is collected.
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

For `codex_cli`, the model is selected by the API and supplied as
`requested_model`; the runtime refuses to use a local model default and passes
the value to `codex exec --model`. It still reads machine-owned environment
settings: `LOUIE_CODEX_COMMAND` defaults to `codex`,
`LOUIE_CODEX_SANDBOX` defaults to `workspace-write`, and
`LOUIE_CODEX_TIMEOUT_SECONDS` defaults to `1800` seconds. Persona and Skill
content comes only from the immutable Activity snapshot supplied by the API;
the runtime does not fetch mutable instruction resources during execution.
Codex/OpenAI authentication remains local to the CLI and does not use API
Linked Services. When Codex startup JSONL exposes a model, the runtime records
it as `actual_model`; otherwise the explicitly requested CLI model is recorded.
For commit-enabled runs, Codex must return a structured final response with a
non-empty `commit_message`. The runtime submits that proposal to the API and
performs Git only if the next checkpoint is `commit_if_allowed`.
