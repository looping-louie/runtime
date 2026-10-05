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
  "poll_interval_seconds": ,
  # Harnesses this runtime is allowed to execute. Each entry has a required
  # kind. CLI Harnesses may set binary to an executable path; it defaults to
  # "codex" or "copilot". Delete unavailable entries. An empty list receives
  # no work.
  # Supported kinds: "louie", "codex_cli", "copilot_cli"
  "harnesses": [
    { "kind": "louie" },
    { "kind": "codex_cli", "binary": "codex" },
    { "kind": "copilot_cli", "binary": "copilot" }
  ],
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
