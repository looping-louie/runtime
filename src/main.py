"""Command-line entry point for runtime configuration checks."""

from __future__ import annotations

import argparse

from clients.activity_client import ActivityRunClient
from clients.pipeline_client import PipelineRunClaimClient
from config import load_config
from executor import ActivityExecutor
from runner import run_forever
from worker import RuntimeWorker


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
    activity_client = ActivityRunClient(api_base_url=config.api_base_url)
    pipeline_client = PipelineRunClaimClient(api_base_url=config.api_base_url)
    worker = RuntimeWorker(
        config=config,
        claim_client=pipeline_client,
        execute_claim=ActivityExecutor(
            activity_client=activity_client,
            pipeline_client=pipeline_client,
        ).execute_claim,
    )
    run_forever(
        worker=worker,
        poll_interval_seconds=config.poll_interval_seconds,
    )
