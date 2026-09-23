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

```sh
pip install .
```

> [!CAUTION]
>
> It is strongly recommended to run the above command in a virtualenv created
> for this project. All subsequent instructions assume you have created and
> activated such virtual environment.
>
> ```sh
> python3 -m venv env
> . env/bin/activate
> ```

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

Start the worker from a normal terminal:

```sh
looping-louie-runtime --config runtime.json
```

On the first normal start, each project without a `worker_id` is provisioned
through `POST /api/v1/workers`; the API-generated ID is written back to this
`runtime.json` configuration file immediately and reused on later starts. Do
not add `worker_id` yourself.

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

Pipeline and Activity checkpoint behavior is documented in
[Pipeline Execution Lifecycle](doc/lifecycle.md).
