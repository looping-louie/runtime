"""Tests for routing frozen Harness checkpoints to local adapters."""

from pathlib import Path

import pytest

from harnesses import executor


def test_execute_harness_routes_codex_v1(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """The common runner delegates Codex checkpoints to the Codex adapter."""

    response = {
        'payload': {
            'harness': {'kind': 'codex_cli', 'version': 'v1', 'config': {}},
        },
    }
    monkeypatch.setattr(
        executor,
        'execute_codex_cli',
        lambda received, checkout: {
            'received': received,
            'checkout': str(checkout),
        },
    )

    assert executor.execute_harness(response, tmp_path) == {
        'received': response,
        'checkout': str(tmp_path),
    }


def test_execute_harness_rejects_an_unknown_adapter(tmp_path: Path) -> None:
    """Unsupported frozen Harnesses fail before local execution begins."""

    with pytest.raises(RuntimeError, match='unsupported Harness'):
        executor.execute_harness({
            'payload': {
                'harness': {'kind': 'future_cli', 'version': 'v1', 'config': {}},
            },
        }, tmp_path)
