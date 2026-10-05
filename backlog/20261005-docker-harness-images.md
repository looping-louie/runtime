# Docker Harness Images

5 October 2026

## Context

The runtime image currently installs Python and Git only. It can execute the
API-directed `louie` Harness, but it cannot execute `codex_cli` or
`copilot_cli` unless the selected CLI is made available by some external
mechanism.

The runtime invokes those CLIs inside the configured Git checkout. The
checkout is intentionally mounted writable because it is the work surface for
repository inspection, file changes, and Git commits. The runtime configuration
directory is also writable because worker provisioning atomically persists a
generated `worker_id`.

The Docker deployment should not depend on host-installed CLI binaries or a
broad host-home mount for CLI configuration, authentication, or session data.

## Motivation

Using host-installed Harness CLIs couples the container to host paths, package
managers, library compatibility, and whichever CLI version happens to be
installed. It makes runtime behavior difficult to reproduce and expands the
host filesystem exposed to the container.

The checkout bind mount remains an intentional capability boundary. The goal is
to remove incidental host filesystem dependencies while preserving the runtime's
ability to work in its configured checkout.

## Proposal

Build and publish explicit runtime images for the supported Harness sets:

* `looping-louie-runtime:louie`: Python runtime and Git only.
* `looping-louie-runtime:codex`: base runtime plus a pinned Codex CLI release.
* `looping-louie-runtime:copilot`: base runtime plus a pinned Copilot CLI release.

Decide whether a combined `codex-copilot` image is needed only after the
single-Harness images are working. Keep the selected Harness executable and its
version discoverable from the image build definition.

Provide CLI authentication at container start through a narrowly scoped,
documented mechanism. Do not bake credentials into images or mount a complete
host home directory. The mechanism must support each CLI's supported
non-interactive authentication flow and persist only the state that is required
between container restarts.

Keep these mounts distinct:

* A writable configuration-directory mount for `runtime.json` and its atomic
  `worker_id` update.
* A writable checkout mount for the configured repository work surface.
* An optional, tool-specific credential or session-state mount when required by
  the selected Harness.

## Scope

This work includes Docker image definitions, pinned CLI installation, supported
authentication and state handling, capability-detection validation, and Docker
documentation.

This work does not change the configured checkout model, replace Git checkout
mounts with API-managed source archives, or redesign runtime checkpoint
execution.

## Open Decisions

* Determine the supported installation and non-interactive authentication flow
  for each pinned CLI version.
* Decide whether session-state persistence is required for normal operation or
  only for optional result enrichment.
* Define the image publishing and version-tagging policy.
* Decide whether runtime configuration remains a bind mount or moves to a named
  volume or external configuration store.

## Acceptance Criteria

* Each supported Harness image contains its declared CLI without relying on a
  host-installed binary.
* CLI and runtime versions are pinned or otherwise reproducibly resolved.
* A container can execute the declared Harness with only the documented
  configuration, checkout, and narrowly scoped credential/state mounts.
* No credential material is embedded in an image layer or requires a full host
  home-directory mount.
* Docker documentation distinguishes `louie`-only and CLI-Harness deployments.
* Containerized capability detection reports only Harnesses that are installed
  and authenticated according to the documented setup.

This backlog item records future work only; it does not request an immediate
change to runtime behavior or Docker deployment.
