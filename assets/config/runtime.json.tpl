{
  # the full URL where the API is listining on
  # Example: "http://127.0.0.1:2000/api/v1"
  "api_base_url": "",
  # the id of the user making the requests. This will be propagated as `X-User-ID`
  # on every API request
  # Example: "local-user",
  "user_id": "",
  # the time (in seconds) between two consecutive requests to the API
  # Example: 2
  "poll_interval_seconds": 2,
  # Harnesses this runtime is allowed to execute. Each item is an object with
  # a required kind. Supported kinds: "louie", "codex_cli", "copilot_cli".
  #
  # Examples:
  #   { "kind": "louie" }
  #   { "kind": "codex_cli" }
  #   { "kind": "copilot_cli", "binary": "/opt/bin/copilot" }
  #
  # binary applies only to codex_cli and copilot_cli. It defaults to "codex"
  # or "copilot" and may name another executable path. Add a CLI Harness only
  # after its local authentication is configured. The Docker image includes
  # both binaries but starts with no declared Harnesses, preventing it from
  # claiming work before this machine is ready. An empty list receives no work.
  "harnesses": [],
  # Each worker maps API projects to local repository checkouts. This keeps a
  # worker from executing a task in an arbitrary directory supplied by an API
  # run.
  "projects": [
    {
      # Replace with the Project ID created in the dashboard or via API
      # Example: "project-id"
      "project_id": "",
      # replace the checkout path with an absolute path to an existing, clean
      # Git checkout.
      # Example: "/absolute/path/to/your/repo"
      "repository_path": ""
    }
  ]
}
