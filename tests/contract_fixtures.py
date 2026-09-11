"""Load mirrored Harness observation contract fixtures."""

from __future__ import annotations

import json
from pathlib import Path


FIXTURE_DIRECTORY = Path(__file__).parent / 'fixtures' / 'harness_observations'


def load_harness_observation(name: str) -> dict[str, object]:
    """Load one normalized observation shared with API and web tests."""

    return json.loads(
        (FIXTURE_DIRECTORY / name).read_text(encoding='utf-8')
    )
