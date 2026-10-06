# Runtime Worker and Project Identity Model

6 October 2026

## Context

The runtime configuration maps each configured Project to a local Git checkout.
Each Project mapping currently persists its own API-generated `worker_id`:

```json
{
  "projects": [
    {
      "project_id": "project-a",
      "repository_path": "/app/data/projects/project-a",
      "worker_id": "worker-a"
    },
    {
      "project_id": "project-b",
      "repository_path": "/app/data/projects/project-b",
      "worker_id": "worker-b"
    }
  ]
}
```

The runtime provisions a Worker through the selected Project context, then uses
that ID with the same Project context for heartbeats and Pipeline claims. The
API persists workers with `project_id`, and worker lookups, readiness, and
capability checks are Project-scoped.

This means one operating runtime process has multiple Worker registrations when
it manages multiple Projects. The current `worker_id` identifies a Project
registration rather than the runtime instance itself.

## Why This Matters

The present model is operationally valid, but it conflates two concepts:

* A runtime instance: one long-lived process or container with a configuration,
  local Harness capabilities, and one or more mounted checkouts.
* A Project enablement: permission for that runtime instance to claim and
  execute work for one Project in one checkout.

Treating each `(project_id, worker_id)` pair as an independent Worker makes the
runtime configuration harder to explain, duplicates liveness and capability
reports, and obscures which runtime process is available across Projects.

A runtime-instance identity could make the control plane answer clearer
questions: which runtime instances are connected, which Harnesses each instance
can execute, and which Projects each instance is enabled to serve.

## Investigation

Perform a cross-repository analysis of `looping-louie-api`,
`looping-louie-runtime`, `looping-louie-cli`, and `looping-louie-app`.

Document the current contract end to end:

* Runtime configuration, first-start provisioning, persisted worker IDs,
  heartbeats, readiness, Pipeline claims, leases, and checkpoint reporting.
* API worker schema, persistence constraints, Project request context, worker
  capability admission, and Pipeline-run ownership/audit fields.
* CLI and application assumptions about Worker IDs, worker readiness, and
  Project scoping.
* Existing migration and backward-compatibility constraints.

Compare at least these models:

1. Preserve Project-scoped Worker registrations, while documenting that a
   runtime process has one registration per enabled Project.
2. Introduce one API-owned runtime-instance Worker identity with explicit
   Project enablements and checkout mappings.
3. Separate runtime-instance liveness/capabilities from a Project-scoped
   execution-agent or authorization record.

For each model, evaluate identity uniqueness, authorization boundaries,
capability reporting, liveness, scheduling and claim validation, failure
isolation, auditability, multi-Project Docker deployment, database migration,
and compatibility with deployed runtimes.

## Non-Goals

This item does not change runtime configuration, worker endpoints, database
schema, Docker deployment, or CLI/application behavior. It records analysis and
a proposed target model before implementation work begins.

## Deliverables

* A written architecture decision that names the selected identity model and
  defines Runtime, Worker, and Project enablement precisely.
* A lifecycle diagram covering provisioning, heartbeat, readiness, claim,
  restart, disablement, and removal.
* A public API and persistence migration proposal, including compatibility and
  rollout strategy for existing Project-scoped worker records.
* A cross-repository implementation plan split into coherent API, runtime, CLI,
  application, test, and documentation changes.

## Acceptance Criteria

* The analysis proves whether a Worker ID identifies a runtime instance, a
  Project registration, or another explicit resource.
* The selected model permits one runtime instance to be enabled for multiple
  Projects without ambiguous authorization or checkout selection.
* Claims cannot be accepted from a runtime that is not enabled for the target
  Project or lacks the frozen Harness capability.
* Liveness and capability semantics remain well-defined for multi-Project
  runtimes and partial failures.
* Existing worker records and deployed runtime configurations have a safe,
  documented migration path.
* The proposal identifies every affected repository and its required contract
  tests.

This backlog item records analysis and design work only; it does not request an
immediate implementation.
