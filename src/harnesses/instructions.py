"""Shared immutable instruction handling for local CLI Harnesses."""

from __future__ import annotations

import json
import re
import shutil
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class CliInstructions:
    """Validated Persona instructions and materialized Skill names."""

    persona_instructions: str
    skill_names: tuple[str, ...]
    materialized_skills: tuple[dict[str, object], ...]


@contextmanager
def materialize_instruction_snapshot(
    checkout_path: Path,
    snapshot: Mapping[str, object],
    *,
    harness_name: str,
    skills_root: Path,
) -> Iterator[CliInstructions]:
    """Expose frozen Skills to one CLI Harness and remove them afterward."""

    persona_instructions, skills = parse_snapshot(snapshot)
    created_roots: list[Path] = []
    created_skills: list[Path] = []
    try:
        if skills:
            for root in _roots_within_checkout(checkout_path, skills_root):
                if not root.exists():
                    root.mkdir()
                    created_roots.append(root)
                elif root.is_symlink() or not root.is_dir():
                    raise ValueError(f'{harness_name} Skill path is not a directory: {root}')
            for name, description, content, _, _ in skills:
                target = skills_root / name
                if target.exists() or target.is_symlink():
                    raise ValueError(
                        f'{harness_name} Skill path already exists in the checkout: {target}'
                    )
                target.mkdir()
                created_skills.append(target)
                (target / 'SKILL.md').write_text(
                    skill_document(name, description, content), encoding='utf-8'
                )
        yield CliInstructions(
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


def _roots_within_checkout(checkout_path: Path, skills_root: Path) -> tuple[Path, ...]:
    """Return missing-parent candidates from checkout to the configured Skill root."""

    relative_root = skills_root.relative_to(checkout_path)
    roots: list[Path] = []
    current = checkout_path
    for part in relative_root.parts:
        current = current / part
        roots.append(current)
    return tuple(roots)


def parse_snapshot(
    snapshot: Mapping[str, object],
) -> tuple[str, tuple[tuple[str, str, str, str, int], ...]]:
    """Validate the API instruction snapshot and normalize safe Skill names."""

    if snapshot.get('snapshot_version') != 1:
        raise ValueError('Activity response has an unsupported instruction snapshot.')
    persona = snapshot.get('persona')
    if not isinstance(persona, Mapping):
        raise ValueError('Instruction snapshot is missing its Persona.')
    persona_instructions = persona.get('content')
    if not isinstance(persona_instructions, str) or not persona_instructions.strip():
        raise ValueError('Instruction snapshot Persona has no instructions.')
    raw_skills = snapshot.get('skills')
    if not isinstance(raw_skills, list):
        raise ValueError('Instruction snapshot Skills must be a list.')
    skills: list[tuple[str, str, str, str, int]] = []
    names: set[str] = set()
    for raw_skill in raw_skills:
        if not isinstance(raw_skill, Mapping):
            raise ValueError('Instruction snapshot contains an invalid Skill.')
        name = skill_name(raw_skill)
        description = raw_skill.get('description')
        content = raw_skill.get('content')
        skill_id = raw_skill.get('id')
        version = raw_skill.get('version')
        if not isinstance(skill_id, str) or not skill_id.strip():
            raise ValueError(f"Instruction snapshot Skill '{name}' has no ID.")
        if not isinstance(version, int) or isinstance(version, bool) or version < 1:
            raise ValueError(f"Instruction snapshot Skill '{name}' has no version.")
        if not isinstance(description, str) or not description.strip():
            raise ValueError(f"Instruction snapshot Skill '{name}' has no description.")
        if not isinstance(content, str) or not content.strip():
            raise ValueError(f"Instruction snapshot Skill '{name}' has no instructions.")
        if name in names:
            raise ValueError(f"Instruction snapshot contains duplicate Skill name '{name}'.")
        names.add(name)
        skills.append((
            name, description.strip(), content.strip(), skill_id.strip(), version,
        ))
    return persona_instructions.strip(), tuple(skills)


def skill_name(skill: Mapping[str, object]) -> str:
    """Convert one display name into a safe repository Skill directory name."""

    source = skill.get('name')
    if not isinstance(source, str) or not source.strip():
        source = skill.get('id')
    if not isinstance(source, str):
        raise ValueError('Instruction snapshot Skill has no name.')
    normalized = re.sub(r'[^a-z0-9]+', '-', source.casefold()).strip('-')
    if not normalized:
        raise ValueError('Instruction snapshot Skill has no usable name.')
    return normalized[:100].rstrip('-')


def skill_document(name: str, description: str, content: str) -> str:
    """Render one valid Harness SKILL.md file with YAML frontmatter."""

    encoded_description = json.dumps(description, ensure_ascii=False)
    return (
        '---\n'
        f'name: {name}\n'
        f'description: {encoded_description}\n'
        '---\n\n'
        f'{content}\n'
    )