# Looping Louie Runtime

The runtime is the worker process that claims queued Pipeline runs from the
Looping Louie API and executes them in configured local Git checkouts.

## Deployment

## Deploy with docker

For a containerized installation, follow the instructions in
[Docker](doc/docker.md).

## Deploy manually

### Installation

Clone this repo and install using pip:

> [!CAUTION]
>
> It is strongly recommended to run the below commands in a virtualenv created
> for this project. All subsequent instructions assume you have created and
> activated such virtual environment.
>
> ```sh
> python3 -m venv env
> . env/bin/activate
> ```

```sh
pip install .
```

### Configuration

Before starting the runtime, create `runtime.json` in the directory where you
will run the commands below. A [template](./assets/config/runtime.json.tpl) for
this file is available at the `assets` directory. You can copy it and fill in
your specific configuration (remove the comments to make it a valid JSON).

```sh
cp assets/config/runtime.json.tpl runtime.json
nano runtime.json
```

A full `runtime.json` configuration file should resemble something like this:

```json
{
  "api_base_url": "http://127.0.0.1:2000/api/v1",
  "user_id": "local-user",
  "poll_interval_seconds": 2,
  "harnesses": [
    { "kind": "louie" }
  ],
  "projects": [
    {
      "project_id": "project-id",
      "repository_path": "/absolute/path/to/checkout"
    }
  ]
}
```

Validate configuration, Git checkout ownership, and a clean worktree before
starting a worker (a silent response means success, any error will be otherwise
printed in console):

```sh
looping-louie-runtime --config runtime.json --check
```

### Execution

Start the worker from a normal terminal:

```sh
looping-louie-runtime --config runtime.json
```

On the first normal start, each project without a `worker_id` is provisioned
through `POST /api/v1/workers`; the API-generated ID is written back to this
`runtime.json` configuration file immediately and reused on later starts. Do
not add `worker_id` yourself.

The worker polls every configured project, claims at most one available run
per project in each cycle, and waits for `poll_interval_seconds` before the
next cycle. A failed project claim or execution is logged without skipping
other configured projects, then retried in the next cycle. Unexpected runtime
defects stop the worker instead of retrying indefinitely.

Pipeline and Activity checkpoint behavior is documented in
[Pipeline Execution Lifecycle](doc/lifecycle.md).

### Harness configuration and availability

The required `harnesses` list in `runtime.json` declares every Harness the
runtime is allowed to execute and publish to the API. Each declaration has a
required `kind`: `louie`, `codex_cli`, or `copilot_cli`. An empty list keeps
the worker connected but unable to claim Harness work. The
[configuration template](assets/config/runtime.json.tpl) documents every
available field.

Startup and `--check` validate every declared CLI Harness:

- `codex_cli` uses its optional `binary` field (default: `codex`) to pass
  `login status`.
- `copilot_cli` uses its optional `binary` field (default: `copilot`) to pass
  `--version`.

The Docker image includes both CLI executables. Installing an executable does
not authenticate it; configure authentication before declaring its Harness in
`runtime.json`.
