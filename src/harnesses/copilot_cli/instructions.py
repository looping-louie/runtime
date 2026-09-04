"""Materialize immutable run instructions for one Copilot CLI turn."""

from __future__ import annotations

import shutil
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from harnesses.codex_cli.instructions import _parse_snapshot, _skill_document


@dataclass(frozen=True, slots=True)
class CopilotInstructions:
    """Validated Persona instructions and materialized Skill names."""

    persona_instructions: str
    skill_names: tuple[str, ...]
    materialized_skills: tuple[dict[str, object], ...]


@contextmanager
def materialize_instruction_snapshot(
    checkout_path: Path,
    snapshot: Mapping[str, object],
) -> Iterator[CopilotInstructions]:
    """Expose frozen Skills to Copilot for one turn and remove them afterward."""

    persona_instructions, skills = _parse_snapshot(snapshot)
    skills_root = checkout_path / '.github' / 'skills'
    created_roots: list[Path] = []
    created_skills: list[Path] = []
    try:
        if skills:
            for root in (checkout_path / '.github', skills_root):
                if not root.exists():
                    root.mkdir()
                    created_roots.append(root)
                elif root.is_symlink() or not root.is_dir():
                    raise ValueError(f'Copilot Skill path is not a directory: {root}')
            for name, description, content, _, _ in skills:
                target = skills_root / name
                if target.exists() or target.is_symlink():
                    raise ValueError(
                        f'Copilot Skill path already exists in the checkout: {target}'
                    )
                target.mkdir()
                created_skills.append(target)
                (target / 'SKILL.md').write_text(
                    _skill_document(name, description, content), encoding='utf-8'
                )
        yield CopilotInstructions(
            persona_instructions=persona_instructions,
            skill_names=tuple(skill[0] for skill in skills),
            materialized_skills=tuple(
                {'id': skill_id, 'name': name, 'version': version}
                for name, _, _, skill_id, version in skills
            ),
        )
    finally:
        for target in reversed(created_skills):
            if target.is_symlink() or target.is_file():
                target.unlink()
            elif target.exists():
                shutil.rmtree(target)
        for root in reversed(created_roots):
            try:
                root.rmdir()
            except OSError:
                pass