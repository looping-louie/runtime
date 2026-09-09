# Looping Louie Runtime Software Architecture

This document describes the software architecture of the Looping Louie Runtime.
The cross-repository product architecture is documented on the
[Looping Louie documentation site](https://loopinglouie.ai/docs/architecture/).
It defines the shared API/runtime ownership boundaries, Worker provisioning,
Harness model, and execution flow.

## Source Structure

Runtime source modules are grouped by ownership. Composition, polling, and
checkpoint orchestration remain directly under `src`, while HTTP adapters and
local Git operations have dedicated packages.

```text
src/
|-- main.py                Builds configured clients, worker, and polling loop
|-- configuration/         Parses configuration and persists provisioned IDs
|-- provisioning.py        Creates missing workers and persists their IDs
|-- polling/               Polls project queues with operational retry
|-- clients/
|   |-- api_client.py      Provides shared authenticated HTTP transport
|   |-- activity_client.py Reads and checkpoints Activity runs over HTTP
|   |-- pipeline_client.py Claims, renews, and advances Pipeline runs over HTTP
|   `-- worker_client.py   Registers workers and sends heartbeats over HTTP
|-- runs/
|   |-- executor.py        Coordinates local checkpoint execution for a claim
|   |-- lease_keepalive.py Renews leases during blocking Harness turns
|   `-- models.py          Defines claimed Pipeline-run values
|-- harnesses/
|   |-- capabilities.py    Detects executable and authenticated Harnesses
|   |-- cli_common.py      Defines shared CLI turn and result-contract helpers
|   |-- executor.py        Routes frozen Harnesses to local adapters
|   |-- instructions.py    Validates and materializes shared instruction snapshots
|   |-- codex_cli/         Runs Codex, materializes instructions, and captures
|   |                      JSONL plus local-session observations
|   |-- copilot_cli/       Runs Copilot, materializes instructions, and captures
|                          JSONL observations
|   `-- louie/             Performs API-directed local checkpoint actions
|-- services/
|   `-- checkout/
|       |-- snapshot.py    Inspects Git state and builds bounded context
|       |-- operations.py  Validates and atomically applies planned writes
|       |-- changes.py     Collects checkout diffs and changed files
|       |-- policy.py      Parses and evaluates local Git commit policy
|       `-- repository.py  Provides shared checkout operations
`-- doc/arquitecture.md    Documents runtime module boundaries
```

Tests follow the same ownership boundaries. Cross-boundary orchestration tests
remain directly under `tests`.

```text
tests/
|-- clients/
|   |-- test_pipeline_client.py
|   |-- test_activity_client.py
|   `-- test_worker_client.py
|-- services/
|   |-- checkout/
|   |   `-- test_changes.py
|   |-- test_codex_cli.py
|   |-- test_copilot_cli.py
|   |-- test_harness_capabilities.py
|   `-- test_harness_execution.py
|-- test_config.py
|-- test_executor.py
|-- test_lease_keepalive.py
|-- test_provisioning.py
|-- test_runner.py
`-- test_worker.py
```

## Composition

`main.py` is the composition root. It loads and validates `RuntimeConfig`,
constructs the cached local-Harness detector, provisions missing workers,
creates the HTTP clients, passes them to `ActivityExecutor`, and constructs
`RuntimeWorker` with the executor callback and capability supplier. It then
invokes `run_forever`.

Dependency flow is:

```text
main -> configuration, capabilities, provisioning, clients, runs, polling
worker -> ClaimClient, executor callback
runs.executor -> activity client, pipeline client, Harness adapters, checkout services
harnesses -> Codex or Copilot CLI adapters, API-directed louie actions
clients -> shared RuntimeApiClient -> HTTP API
services.checkout -> configured Git checkout
```

The worker and executor depend on protocols rather than concrete HTTP clients.
Tests use those protocols to isolate polling and checkpoint behavior from HTTP.

## Architectural Inspection Points

Future architecture reviews can use these boundaries to locate responsibility
drift:

**Composition.** `main.py` remains wiring only; it does not acquire execution
rules.

**Polling.** `polling/worker.py` remains responsible for Project polling,
heartbeats, and error isolation, not checkpoint behavior.

**Run orchestration.** `runs/executor.py` remains the orchestration point for
the local half of the checkpoint protocol, including lease renewal and
Pipeline continuation.

**Harness routing.** `harnesses/executor.py` routes only frozen `run_harness`
turns to CLI adapters. The `harnesses/louie` package performs API-directed local
checkpoint actions.

**Local checkout services.** The `services.checkout` package owns repository
context, file operations, diffs, and commit policy without HTTP or scheduling
concerns.

**HTTP clients.** The `clients` package contains transport adapters over the
shared `RuntimeApiClient` and does not perform filesystem or Git operations.

**New actions.** New API-directed checkpoint actions require a handler in
`harnesses/louie` and a corresponding API checkpoint contract. New Harness
kinds require an adapter in `harnesses`.

**Persistence.** New local persistence requires an ownership decision because
the API is currently the sole durable execution-state authority.

## Related Runtime Documentation

- [Runtime README](../README.md#execution) documents configuration and local
  checkpoint execution.
- [Pipeline Execution Lifecycle](lifecycle.md) describes the API/runtime state
  transition protocol and failure ownership.
- [Worker Overview](worker-overview.md) documents provisioning, heartbeats,
  capabilities, and Pipeline-run leases.
