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
