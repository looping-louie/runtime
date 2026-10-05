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
For example, keep `harnesses` as `['louie']` until Codex and Copilot
authentication are available, then add `codex_cli` or `copilot_cli`.

## Start the runtime

The runtime needs writable access to its configuration directory and each Git
checkout it manages. Set `repository_path` in the runtime JSON configuration to
the checkout path inside the container, then start the worker:

```sh
export REPO_PATH=/absolute/path/to/checkout
export CONFIG_PATH="$PWD/runtime-config"

docker run --rm \
  --user "$(id -u):$(id -g)" \
  --add-host host.docker.internal:host-gateway \
  -v "$CONFIG_PATH:/runtime-config" \
  -v "$CHECKOUT_PATH:/workspaces/project" \
  looping-louie-runtime:latest \
  --config /runtime-config/runtime.json
```

For the command above, `runtime-config/runtime.json` must contain a project
mapping whose `repository_path` is `/workspaces/project`:

```json
{
  "api_base_url": "http://host.docker.internal:2000/api/v1",
  "user_id": "local-user",
  "poll_interval_seconds": 2,
  "harnesses": ["louie"],
  "projects": [
    {
      "project_id": "local-project",
      "repository_path": "/workspaces/project"
    }
  ]
}
```

The runtime registers missing workers and atomically writes the generated
`worker_id` to its configuration. Mount the containing `runtime-config`
directory rather than mounting `runtime.json` as an individual file, so that
write succeeds.

The `--user` option makes files created in the mounted configuration directory
and checkout belong to the current host user.
