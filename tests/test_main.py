"""Tests for runtime command-line parsing helpers."""

from __future__ import annotations

import argparse

import pytest

from main import _project_mapping


def test_project_mapping_parses_a_project_id_and_checkout_path() -> None:
    """The repeatable project flag keeps a checkout path after its first colon."""

    assert _project_mapping('project-1:/app/data/projects/project:archive') == (
        'project-1',
        '/app/data/projects/project:archive',
    )


@pytest.mark.parametrize('value', ('project-1', ':checkout', 'project-1:'))
def test_project_mapping_rejects_an_incomplete_mapping(value: str) -> None:
    """Each project flag requires both a Project ID and a checkout path."""

    with pytest.raises(argparse.ArgumentTypeError, match='PROJECT_ID:REPOSITORY_PATH'):
        _project_mapping(value)
