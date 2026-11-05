# Looping Louie Runtime

The runtime is the worker process that claims queued Pipeline runs from the
Looping Louie API and executes them in configured local Git checkouts.

## Deployment

### Deploy with docker

For a containerized installation, follow the instructions in
[Docker](doc/docker.md).

### Deploy manually

#### Installation

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

For repeatable development commands, use:

```sh
make install
make test
make check
make build
```

#### Configuration

Before starting the runtime, create `.env.json` in the directory where you
will run the commands below. A [template](./assets/config/.env.json.tpl) for
this file is available at the `assets` directory. You can copy it and fill in
your specific configuration. Remove its comments to make it valid JSON.

```sh
cp assets/config/.env.json.tpl .env.json
nano .env.json
```

A full `.env.json` configuration file should resemble something like this:

```json
{
  "api_base_url": "http://127.0.0.1:2000/api/v1",
  "service_account_token": "service-account-token",
  "poll_interval_seconds": 2,
  "harnesses": [
    {
      "kind": "louie"
    }
  ],
  "projects": [
    {
      "project_id": "project-id",
      "repository_path": "/absolute/path/to/checkout"
    }
  ]
}
```

Create one service account for each runtime deployment in **Settings → Service
accounts**. Select the projects that runtime may execute, copy its one-time
token, and store it as `service_account_token`. Do not use a human account ID
or a personal access token for a runtime.

Validate configuration, Git checkout ownership, and a clean worktree before
starting a worker (a silent response means success, any error will be otherwise
printed in console):

```sh
make check
```

#### Execution

Start the worker from a normal terminal:

```sh
looping-louie-runtime
```

On the first normal start, the runtime registers one Worker through
`POST /api/v1/workers`; its API-generated ID is written to the top
level of `.env.json` immediately. Every configured Project is then enabled
for that Worker. Later starts reuse the ID and safely reconcile the same
Project enablements. Do not add `worker_id` yourself. If the API is unavailable
during startup or reconciliation, the process logs the failed attempt and
retries after `poll_interval_seconds` instead of terminating.

The worker polls every configured project, claims at most one available run
per project in each cycle, and waits for `poll_interval_seconds` before the
next cycle. A failed project claim or execution is logged without skipping
other configured projects, then retried in the next cycle. Unexpected runtime
defects stop the worker instead of retrying indefinitely.

Pipeline and Activity checkpoint behavior is documented in
[Pipeline Execution Lifecycle](doc/lifecycle.md).

## Harness configuration and availability

The required `harnesses` list in `.env.json` declares every Harness the
runtime is allowed to execute and publish to the API (an empty list keeps
the worker connected but unable to claim Harness work). The
[configuration template](assets/config/.env.json.tpl) documents every
available field.

Startup and `looping-louie-runtime-check` validate every declared CLI Harness:

- `codex_cli` uses its optional `binary` field (default: `codex`) to pass
  `login status`.
- `copilot_cli` uses its optional `binary` field (default: `copilot`) to pass
  `--version`.

The Docker image includes both CLI executables. Installing an executable does
not authenticate it; configure authentication before declaring its Harness in
`.env.json`.
