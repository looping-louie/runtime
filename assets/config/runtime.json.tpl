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
  # Each worker maps API projects to local repository checkouts. This keeps a
  # worker from executing a task in an arbitrary directory supplied by an API
  # run.
  projects: [
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
