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
|   |-- pipeline_client.py
|   |                       Claims, renews, and advances Pipeline runs over HTTP
|   `-- activity_client.py Reads and checkpoints Activity runs over HTTP
|-- executor.py            Coordinates local checkpoint execution for a claim
|-- harnesses/
|   |-- capabilities.py    Detects executable and authenticated Harnesses
|   |-- cli_common.py      Defines shared CLI turn and result-contract helpers
|   |-- executor.py        Routes frozen Harnesses to local adapters
|   |-- instructions.py    Validates and materializes shared instruction snapshots
|   |-- codex_cli/         Runs Codex, materializes instructions, and captures
|   |                      JSONL plus local-session observations
|   `-- copilot_cli/       Runs Copilot, materializes instructions, and captures
|                          JSONL observations
|-- services/
|   `-- git/
|       |-- repository_context.py  Inspects Git state and builds bounded context
|       |-- file_operations.py     Validates and atomically applies planned writes
|       `-- policy.py              Parses and evaluates local Git commit policy
`-- doc/arquitecture.md    Documents runtime module boundaries
```

Tests follow the same ownership boundaries. Cross-boundary orchestration tests
remain directly under `tests`.

```text
tests/
|-- clients/
|   |-- test_pipeline_client.py
|   `-- test_activity_client.py
|-- services/
|   `-- git/
|       `-- test_repository_context.py
|-- test_config.py
|-- test_executor.py
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
main -> configuration, capabilities, provisioning, clients, executor, polling
worker -> ClaimClient, executor callback
executor -> activity client, pipeline client, services.git
clients -> HTTP API
services.git -> configured Git checkout
```

The worker and executor depend on protocols rather than concrete HTTP clients.
Tests use those protocols to isolate polling and checkpoint behavior from HTTP.

## Architectural Inspection Points

Future architecture reviews can use these boundaries to locate responsibility
drift:

**Composition.** `main.py` remains wiring only; it does not acquire execution
rules.

**Polling.** `worker.py` remains responsible for project polling and error
isolation, not checkpoint behavior.

**Checkpoint orchestration.** `executor.py` remains the orchestration point for
the local half of the checkpoint protocol.

**Local Git services.** The `services.git` package owns repository context,
file operations, and commit policy without HTTP or scheduling concerns.

**HTTP clients.** The `clients` package contains transport adapters and does
not perform filesystem or Git operations.

**New actions.** New Activity action types require an explicit executor action
handler and a corresponding API checkpoint contract.

**Persistence.** New local persistence requires an ownership decision because
the API is currently the sole durable execution-state authority.

## Related Runtime Documentation

- [Runtime README](../README.md#execution) documents configuration and local
  checkpoint execution.
- [Pipeline Execution Lifecycle](lifecycle.md) describes the API/runtime state
  transition protocol and failure ownership.
- [Worker Overview](worker-overview.md) documents provisioning, heartbeats,
  capabilities, and Pipeline-run leases.
