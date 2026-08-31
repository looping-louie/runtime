"""Command-line entry point for runtime configuration checks."""

from __future__ import annotations

import argparse

from clients.activity_client import ActivityRunClient
from clients.pipeline_client import PipelineRunClaimClient
from clients.worker_client import WorkerHeartbeatClient
from configuration.runtime import load_config
from harnesses.capabilities import detect_harness_capabilities
from polling.loop import run_forever
from polling.worker import RuntimeWorker
from provisioning import provision_missing_workers
from runs.executor import ActivityExecutor


def main() -> None:
    """Validate configuration and run the configured runtime worker indefinitely."""

    parser = argparse.ArgumentParser(description='Looping Louie runtime worker.')
    parser.add_argument('--config', required=True, help='Path to runtime JSON configuration.')
    parser.add_argument(
        '--check',
        action='store_true',
        help='Validate configured checkouts without starting a worker.',
    )
    arguments = parser.parse_args()
    config = load_config(arguments.config)
    config.validate_checkouts()
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
            harnesses=detect_harness_capabilities(),
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
        ).execute_claim,
    )
    run_forever(
        worker=worker,
        poll_interval_seconds=config.poll_interval_seconds,
    )
