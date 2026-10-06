"""Command-line entry point for runtime configuration checks."""

from __future__ import annotations

import argparse
from functools import partial
from pathlib import Path

from clients.activity_client import ActivityRunClient
from clients.pipeline_client import PipelineRunClaimClient
from clients.worker_client import WorkerHeartbeatClient
from configuration.runtime import initialize_config, load_config
from harnesses.capabilities import validate_harness_capabilities
from harnesses.executor import execute_harness
from polling.loop import run_forever
from polling.worker import RuntimeWorker
from provisioning import provision_missing_workers
from runs.executor import ActivityExecutor


DEFAULT_DOCKER_CONFIG = Path('/app/default-runtime.json')


def main() -> None:
    """Validate configuration and run the configured runtime worker indefinitely."""

    parser = argparse.ArgumentParser(description='Looping Louie runtime worker.')
    parser.add_argument('--config', required=True, help='Path to runtime JSON configuration.')
    parser.add_argument(
        '--api-base-url',
        help='API base URL used only to create a missing runtime configuration.',
    )
    parser.add_argument(
        '--user-id',
        help='User ID used only to create a missing runtime configuration.',
    )
    parser.add_argument(
        '--project-id',
        help='Project ID used only to create a missing runtime configuration.',
    )
    parser.add_argument(
        '--repository-path',
        help='Checkout path used only to create a missing runtime configuration.',
    )
    parser.add_argument(
        '--harness',
        action='append',
        choices=('louie', 'codex_cli', 'copilot_cli'),
        default=[],
        help='Declared Harness used only to create a missing runtime configuration.',
    )
    parser.add_argument(
        '--poll-interval-seconds',
        type=float,
        help='Polling interval used only to create a missing runtime configuration.',
    )
    parser.add_argument(
        '--check',
        action='store_true',
        help='Validate configured checkouts without starting a worker.',
    )
    arguments = parser.parse_args()
    initialize_config(
        arguments.config,
        defaults_path=DEFAULT_DOCKER_CONFIG,
        api_base_url=arguments.api_base_url,
        user_id=arguments.user_id,
        project_id=arguments.project_id,
        repository_path=arguments.repository_path,
        harnesses=tuple(arguments.harness),
        poll_interval_seconds=arguments.poll_interval_seconds,
    )
    config = load_config(arguments.config)
    config.validate_checkouts()
    validate_harness_capabilities(config.harnesses)
    if arguments.check:
        return
    worker_client = WorkerHeartbeatClient(
        api_base_url=config.api_base_url,
        user_id=config.user_id,
    )
    if any(project.worker_id is None for project in config.projects):
        config = provision_missing_workers(
            config_path=arguments.config,
            config=config,
            client=worker_client,
            harnesses=config.harness_kinds,
        )
    activity_client = ActivityRunClient(
        api_base_url=config.api_base_url,
        user_id=config.user_id,
    )
    pipeline_client = PipelineRunClaimClient(
        api_base_url=config.api_base_url,
        user_id=config.user_id,
    )
    worker = RuntimeWorker(
        config=config,
        claim_client=pipeline_client,
        heartbeat_client=worker_client,
        execute_claim=ActivityExecutor(
            activity_client=activity_client,
            pipeline_client=pipeline_client,
            harness_runner=partial(execute_harness, binaries=config.harness_binaries),
        ).execute_claim,
    )
    run_forever(
        worker=worker,
        poll_interval_seconds=config.poll_interval_seconds,
    )
