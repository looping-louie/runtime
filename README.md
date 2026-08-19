# Looping Louie Runtime

The runtime is the worker process that claims queued Pipeline runs from the
Looping Louie API and executes them in configured local Git checkouts.

## Configuration

Each worker maps API workspaces to local repository checkouts. This keeps a
worker from executing a task in an arbitrary directory supplied by an API run.

```json
{
	"api_base_url": "http://127.0.0.1:8000/api/v1",
	"worker_id": "runtime-local-01",
	"poll_interval_seconds": 2,
	"workspaces": [
		{
			"workspace_id": "local-workspace",
			"repository_path": "/absolute/path/to/checkout"
		}
	]
}
```

Validate configuration and checkout ownership before starting a worker:

```sh
looping-louie-runtime --config runtime.json --check
```

Start the worker from a normal terminal:

```sh
looping-louie-runtime --config runtime.json
```

The worker polls every configured workspace, claims at most one available run
per workspace in each cycle, and waits for `poll_interval_seconds` before the
next cycle. A failed poll is logged and retried in the next cycle.

## Execution

For a claimed Activity run, the runtime performs these checkpoint actions in
the mapped checkout:

- `collect_snapshot`: sends bounded repository context, project metadata, and
	the checkout constitution to the API.
- `apply_operations`: validates and atomically applies API-provided file
	operations without permitting checkout escape or symbolic-link traversal.
- `submit_review_input`: sends the final Git diff and bounded changed-file
	contents.
- `commit_if_allowed`: enforces local `louie.yaml` Git policy, then commits an
	API-approved change when allowed.

The runtime never selects a checkout from an API response. It uses only the
workspace-to-checkout mapping in its local configuration.
