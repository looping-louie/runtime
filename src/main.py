"""Command-line entry point for runtime configuration checks."""

from __future__ import annotations

import argparse

from config import load_config


def main() -> None:
    """Validate runtime configuration before starting a worker process."""

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
    raise SystemExit('Runtime execution is not configured yet. Use --check.')