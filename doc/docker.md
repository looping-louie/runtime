# Docker

## Build the runtime image

Build the image from the repository root:

```sh
docker build -t looping-louie-runtime:latest .
```

## Start the runtime

The runtime needs writable access to its configuration directory and each Git
checkout it manages. Set `repository_path` in the runtime JSON configuration to
the checkout path inside the container, then start the worker:

```sh
export CHECKOUT_PATH=/absolute/path/to/checkout

docker run --rm \
  --user "$(id -u):$(id -g)" \
  --add-host host.docker.internal:host-gateway \
  -v "$PWD/runtime-config:/runtime-config" \
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
