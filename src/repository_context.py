"""Build bounded repository context for Activity snapshot checkpoints."""

from __future__ import annotations

import subprocess
from collections import Counter
from pathlib import Path


IGNORED_DIRECTORIES = frozenset({
    '.git', '.looping-louie', 'node_modules', '.nuxt', 'dist', 'build',
    '.venv', 'venv', '__pycache__',
})
SOURCE_EXTENSIONS = frozenset({
    '.py', '.js', '.ts', '.vue', '.html', '.css', '.scss', '.md', '.json',
    '.toml', '.yaml', '.yml',
})
MAX_SNAPSHOT_FILES = 40
MAX_SNAPSHOT_FILE_CHARS = 8_000
MAX_SNAPSHOT_TOTAL_CHARS = 220_000
MAX_REVIEW_FILES = 120
MAX_REVIEW_FILE_CHARS = 120_000
MAX_TOTAL_REVIEW_CHARS = 1_200_000


def build_repository_context(checkout_path: Path) -> str:
    """Return bounded repository context for deterministic API operation planning."""

    root = checkout_path.resolve()
    changed_files = get_changed_files(root)
    files_block = '\n'.join(changed_files) if changed_files else '(no changed files)'
    return (
        'Current repository snapshot\n'
        f'Repository tree (top-level):\n{_repository_tree(root)}\n\n'
        f'Changed files:\n{files_block}\n\n'
        f'Current diff:\n{get_git_diff(root)}\n\n'
        'Selected file contents (for deterministic patching):\n'
        f'{_snapshot_source_files(root)}'
    )


def build_project_profile(checkout_path: Path) -> dict[str, object]:
    """Return compact structural signals about one configured checkout."""

    root = checkout_path.resolve()
    extension_counts: Counter[str] = Counter()
    source_file_count = 0
    approximate_source_chars = 0
    for path in _source_files(root):
        source_file_count += 1
        extension_counts[path.suffix.lower() or '[none]'] += 1
        try:
            approximate_source_chars += path.stat().st_size
        except OSError:
            continue
    return {
        'source_file_count': source_file_count,
        'approximate_source_chars': approximate_source_chars,
        'extension_counts': dict(extension_counts),
        'top_level_entries': _top_level_entries(root),
        'markers': {
            'nuxt': (root / 'nuxt.config.ts').exists() or (root / 'nuxt.config.js').exists(),
            'package_json': (root / 'package.json').exists(),
            'fastapi': _contains_text(root / 'requirements.txt', 'fastapi')
            or _contains_text(root / 'pyproject.toml', 'fastapi'),
            'docker': any((root / name).exists() for name in ('Dockerfile', 'docker-compose.yml', 'compose.yml')),
            'tests': any((root / name).exists() for name in ('tests', 'test', '__tests__')),
        },
    }


def get_head_sha(checkout_path: Path) -> str:
    """Return the configured checkout's current Git commit SHA."""

    return _git(checkout_path, 'rev-parse', 'HEAD')


def get_current_branch(checkout_path: Path) -> str:
    """Return the current non-detached branch for one configured checkout."""

    return _git(checkout_path, 'symbolic-ref', '--quiet', '--short', 'HEAD').strip()


def has_changes(checkout_path: Path) -> bool:
    """Return whether the checkout has staged, unstaged, or untracked changes."""

    return bool(_git(checkout_path, 'status', '--porcelain').strip())


def commit_all(checkout_path: Path, message: str) -> str:
    """Stage and commit every pending checkout change, returning its new SHA."""

    _git(checkout_path, 'add', '--all')
    _git(checkout_path, 'commit', '-m', message)
    return get_head_sha(checkout_path)


def get_git_diff(checkout_path: Path) -> str:
    """Return the current checkout diff, including untracked files."""

    _git(checkout_path, 'add', '-N', '.')
    return _git(checkout_path, 'diff', '--binary', 'HEAD')


def get_changed_files(checkout_path: Path) -> list[str]:
    """Return checkout paths changed from HEAD, including untracked files."""

    _git(checkout_path, 'add', '-N', '.')
    return [line for line in _git(checkout_path, 'diff', '--name-only', 'HEAD').splitlines() if line]


def load_constitution(checkout_path: Path) -> str:
    """Read a checkout-local constitution or return the runtime default."""

    path = checkout_path / '.looping-louie' / 'constitution.md'
    if not path.exists():
        return (
            'Implement only the requested task.\n'
            'Avoid unrelated changes.\n'
            'Preserve existing behaviour unless explicitly requested.\n'
            'Blocking issues must describe concrete defects rather than preferences.\n'
            'Never expose secrets or introduce clear security vulnerabilities.'
        )
    return path.read_text(encoding='utf-8').strip()


def read_changed_file_contents(
    checkout_path: Path,
    changed_files: list[str],
) -> dict[str, str]:
    """Return bounded UTF-8 content for changed files supplied to reviewers."""

    root = checkout_path.resolve()
    contents: dict[str, str] = {}
    total_chars = 0
    for relative_path in changed_files[:MAX_REVIEW_FILES]:
        path = (root / relative_path).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            continue
        try:
            content = path.read_text(encoding='utf-8')
        except (OSError, UnicodeDecodeError):
            continue
        if len(content) > MAX_REVIEW_FILE_CHARS:
            content = f'{content[:MAX_REVIEW_FILE_CHARS]}\n\n[TRUNCATED]'
        if total_chars + len(content) > MAX_TOTAL_REVIEW_CHARS:
            break
        contents[relative_path] = content
        total_chars += len(content)
    return contents


def _git(checkout_path: Path, *arguments: str) -> str:
    """Run one Git command and return stdout or raise a contextual error."""

    result = subprocess.run(
        ['git', '-C', str(checkout_path), *arguments],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        return result.stdout
    detail = result.stderr.strip() or result.stdout.strip()
    raise RuntimeError(f'Git command failed: {detail or "unknown error"}')


def _repository_tree(root: Path) -> str:
    """Return stable top-level entries excluding generated directories."""

    return '\n'.join(_top_level_entries(root)) or '(no files found)'


def _top_level_entries(root: Path) -> list[str]:
    """Return up to 80 stable top-level entry names."""

    return [
        f'{path.name}{"/" if path.is_dir() else ""}'
        for path in sorted(root.iterdir(), key=lambda item: item.name.lower())
        if path.name not in IGNORED_DIRECTORIES
    ][:80]


def _snapshot_source_files(root: Path) -> str:
    """Return bounded eligible source file content blocks."""

    chunks: list[str] = []
    total_chars = 0
    for path in _source_files(root):
        if len(chunks) >= MAX_SNAPSHOT_FILES:
            break
        try:
            content = path.read_text(encoding='utf-8')
        except (OSError, UnicodeDecodeError):
            continue
        if len(content) > MAX_SNAPSHOT_FILE_CHARS:
            content = f'{content[:MAX_SNAPSHOT_FILE_CHARS]}\n\n[TRUNCATED]'
        relative_path = path.relative_to(root).as_posix()
        block = f'--- FILE: {relative_path} ---\n{content}\n--- END FILE: {relative_path} ---\n'
        if total_chars + len(block) > MAX_SNAPSHOT_TOTAL_CHARS:
            break
        chunks.append(block)
        total_chars += len(block)
    return '\n'.join(chunks) if chunks else '(no source files captured)'


def _source_files(root: Path) -> list[Path]:
    """Return eligible source files in stable path order."""

    return [
        path
        for path in sorted(root.rglob('*'))
        if path.is_file()
        and path.suffix.lower() in SOURCE_EXTENSIONS
        and not any(part in IGNORED_DIRECTORIES for part in path.relative_to(root).parts)
    ]


def _contains_text(path: Path, text: str) -> bool:
    """Return whether a small configuration file contains one marker."""

    try:
        return path.is_file() and text in path.read_text(encoding='utf-8').lower()
    except (OSError, UnicodeDecodeError):
        return False
