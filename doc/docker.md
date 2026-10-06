# Docker

## Build the runtime image

Build the image from the repository root:

```sh
docker build -t looping-louie-runtime:latest .
```

The image includes the `codex` and `copilot` executables. Their pinned package
versions can be replaced at build time:

```sh
docker build \
  --build-arg CODEX_CLI_VERSION=0.160.0 \
  --build-arg COPILOT_CLI_VERSION=1.0.91 \
  -t looping-louie-runtime:latest .
```

Installing an executable does not authenticate it. Declare only the Harnesses
that are configured and authenticated for this container in `runtime.json`.
For example, use `[{'kind': 'codex_cli'}]` only after Codex authentication is
available. Use `[]` for a connected worker that must not receive Harness work.

## Start the runtime

The image creates `/app/config/runtime.json` during its first start from
the shared [configuration template](../assets/config/runtime.json.tpl). Mount a
writable configuration directory and each Git checkout the worker manages:

```sh
export REPO_PATH=/absolute/path/to/checkout/folder
export CONFIG_PATH=/absolute/path/to/config/folder

docker run --rm \
  --user "$(id -u):$(id -g)" \
  --add-host host.docker.internal:host-gateway \
  -v "$CONFIG_PATH:/app/config" \
  -v "$REPO_PATH:/app/data/workspaces/project" \
  looping-louie-runtime:latest \
  --api-base-url http://host.docker.internal:2000/api/v1 \
  --user-id local-user \
  --project-id local-project \
  --repository-path /app/data/workspaces/project \
  --harness louie
```

The image has a default `--config /app/config/runtime.json` command. The
first-start flags create that file from image defaults with the supplied API,
User, Project, checkout, and Harness values. Repeated `--harness` flags declare
multiple capabilities, such as `--harness codex_cli --harness copilot_cli`.

After the first start, the runtime reuses the existing configuration and
ignores these initialization flags. Change configuration by editing or removing
`config/runtime.json`; never mount that file individually. The runtime
registers missing workers and atomically writes the generated `worker_id` to
the mounted configuration directory.

The `--user` option makes files created in the mounted configuration directory
and checkout belong to the current host user.
