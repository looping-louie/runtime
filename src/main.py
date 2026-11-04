"""Command-line entry point for runtime configuration checks."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from functools import partial
from pathlib import Path

from clients.activity_client import ActivityRunClient
from clients.pipeline_client import PipelineRunClaimClient
from clients.worker_client import WorkerHeartbeatClient
from configuration.runtime import RuntimeConfig, initialize_config, load_config
from harnesses.capabilities import validate_harness_capabilities
from harnesses.executor import execute_harness
from polling.loop import run_forever
from polling.worker import RuntimeWorker
from provisioning import ProvisioningRuntimeWorker
from runs.executor import ActivityExecutor


DEFAULT_CONFIG_PATH = Path('.env.json')
DEFAULT_DOCKER_CONFIG = Path('/app/assets/default.env.json')


def _project_mapping(value: str) -> tuple[str, str]:
    """Parse one first-start Project ID and checkout path mapping."""

    project_id, separator, repository_path = value.partition(':')
    if not separator or not project_id or not repository_path:
        raise argparse.ArgumentTypeError(
            'project must use PROJECT_ID:REPOSITORY_PATH format.',
        )
    return project_id, repository_path


def _parse_run_arguments(arguments: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse persistent runtime CLI arguments."""

    parser = argparse.ArgumentParser(description='Looping Louie runtime worker.')
    parser.add_argument(
        '--config',
        default=DEFAULT_CONFIG_PATH,
        help='Path to runtime JSON configuration (default: .env.json).',
    )
    parser.add_argument(
        '--api-base-url',
        help='API base URL used only to create a missing runtime configuration.',
    )
    parser.add_argument(
        '--user-id',
        help='User ID used only to create a missing runtime configuration.',
    )
    parser.add_argument(
        '--project',
        action='append',
        type=_project_mapping,
        default=[],
        metavar='PROJECT_ID:REPOSITORY_PATH',
        help='Project checkout mapping used only to create a missing runtime configuration.',
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
    return parser.parse_args(arguments)


def _parse_check_arguments(arguments: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse runtime configuration-check CLI arguments."""

    parser = argparse.ArgumentParser(
        description='Validate a Looping Louie runtime configuration.',
    )
    parser.add_argument(
        '--config',
        default=DEFAULT_CONFIG_PATH,
        help='Path to runtime JSON configuration (default: .env.json).',
    )
    return parser.parse_args(arguments)


def _validate_config(config_path: str | Path) -> RuntimeConfig:
    """Load and validate a runtime configuration and its local dependencies."""

    config = load_config(config_path)
    config.validate_checkouts()
    validate_harness_capabilities(config.harnesses)
    return config


def check() -> None:
    """Validate a runtime configuration without starting a persistent worker."""

    arguments = _parse_check_arguments()
    _validate_config(arguments.config)


def run() -> None:
    """Initialize configuration and run the configured runtime worker indefinitely."""

    arguments = _parse_run_arguments()
    initialize_config(
        arguments.config,
        defaults_path=DEFAULT_DOCKER_CONFIG,
        api_base_url=arguments.api_base_url,
        user_id=arguments.user_id,
        projects=tuple(arguments.project),
        harnesses=tuple(arguments.harness),
        poll_interval_seconds=arguments.poll_interval_seconds,
    )
    config = _validate_config(arguments.config)
    worker_client = WorkerHeartbeatClient(
        api_base_url=config.api_base_url,
        user_id=config.user_id,
    )
    activity_client = ActivityRunClient(
        api_base_url=config.api_base_url,
        user_id=config.user_id,
    )
    pipeline_client = PipelineRunClaimClient(
        api_base_url=config.api_base_url,
        user_id=config.user_id,
    )
    def create_worker(provisioned_config: RuntimeConfig) -> RuntimeWorker:
        """Build the polling worker after the API assigns a Worker identity."""

        return RuntimeWorker(
            config=provisioned_config,
            claim_client=pipeline_client,
            heartbeat_client=worker_client,
            execute_claim=ActivityExecutor(
                activity_client=activity_client,
                pipeline_client=pipeline_client,
                harness_runner=partial(
                    execute_harness,
                    binaries=provisioned_config.harness_binaries,
                ),
            ).execute_claim,
        )

    worker = ProvisioningRuntimeWorker(
        config_path=arguments.config,
        config=config,
        client=worker_client,
        harnesses=config.harness_kinds,
        worker_factory=create_worker,
    )
    run_forever(
        worker=worker,
        poll_interval_seconds=config.poll_interval_seconds,
    )
