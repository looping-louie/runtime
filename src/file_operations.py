"""Validate and atomically apply API-planned file operations in a checkout."""

from __future__ import annotations

from pathlib import Path, PurePosixPath


ALLOWED_OPERATIONS = frozenset({'create', 'replace', 'replace_text', 'delete'})


def apply_file_operations(
    checkout_path: Path,
    operations: list[object],
) -> None:
    """Validate all operations before atomically applying them to one checkout."""

    root = checkout_path.resolve()
    if not root.is_dir():
        raise ValueError(f'Repository root is not a directory: {root}')
    pending: dict[Path, str | None] = {}
    for operation in operations:
        _validate_operation(operation)
        assert isinstance(operation, dict)
        target = _safe_path(root, operation['path'])
        current_content = _read_pending_content(target=target, pending=pending)
        action = operation['operation']
        if action == 'create':
            if current_content is not None:
                raise ValueError(f'Cannot create existing file: {operation["path"]}')
            pending[target] = operation['content']
        elif action == 'replace':
            if current_content is None:
                raise ValueError(f'Cannot replace missing file: {operation["path"]}')
            pending[target] = operation['content']
        elif action == 'replace_text':
            if current_content is None:
                raise ValueError(f'Cannot modify missing file: {operation["path"]}')
            old_content = operation['old_content']
            matches = current_content.count(old_content)
            if matches == 0:
                raise ValueError(f'replace_text old_content was not found in {operation["path"]}')
            if matches > 1:
                raise ValueError(f'replace_text old_content appears more than once in {operation["path"]}')
            pending[target] = current_content.replace(old_content, operation['new_content'], 1)
        else:
            if current_content is None:
                raise ValueError(f'Cannot delete missing file: {operation["path"]}')
            pending[target] = None
    _commit_pending_changes(pending)


def _validate_operation(operation: object) -> None:
    """Require one complete, normalized API operation object."""

    if not isinstance(operation, dict):
        raise ValueError('Each operation must be an object.')
    action = operation.get('operation')
    path = operation.get('path')
    if action not in ALLOWED_OPERATIONS:
        raise ValueError(f'Invalid operation: {action}')
    if not isinstance(path, str) or not path:
        raise ValueError('Operation path must be a non-empty string.')
    normalized_path = str(PurePosixPath(path))
    if path.startswith('/') or '\x00' in path or '\\' in path or normalized_path != path:
        raise ValueError(f'Operation path must use normalized relative POSIX syntax: {path}')
    if '..' in Path(path).parts:
        raise ValueError(f'Parent path traversal is not allowed: {path}')
    allowed_fields = {
        'create': {'operation', 'path', 'content'},
        'replace': {'operation', 'path', 'content'},
        'replace_text': {'operation', 'path', 'old_content', 'new_content'},
        'delete': {'operation', 'path'},
    }[action]
    unknown_fields = sorted(set(operation) - allowed_fields)
    if unknown_fields:
        raise ValueError(f'{action} operation contains unexpected fields: {", ".join(unknown_fields)}')
    if action in {'create', 'replace'} and not isinstance(operation.get('content'), str):
        raise ValueError(f'{action} operation requires string content.')
    if action == 'replace_text':
        if not isinstance(operation.get('old_content'), str) or not operation['old_content']:
            raise ValueError('replace_text operation requires non-empty old_content.')
        if not isinstance(operation.get('new_content'), str):
            raise ValueError('replace_text operation requires string new_content.')


def _safe_path(root: Path, relative_path: str) -> Path:
    """Return a non-symlink checkout path while preventing directory escape."""

    target = root.joinpath(*PurePosixPath(relative_path).parts)
    current = root
    for part in PurePosixPath(relative_path).parts:
        current = current / part
        if current.is_symlink():
            raise ValueError(f'Path cannot traverse symbolic links: {relative_path}')
    try:
        target.resolve(strict=False).relative_to(root)
    except ValueError as exc:
        raise ValueError(f'Path escapes repository: {relative_path}') from exc
    return target


def _read_pending_content(*, target: Path, pending: dict[Path, str | None]) -> str | None:
    """Return simulated current content for one target before mutation."""

    if target in pending:
        return pending[target]
    if target.is_symlink():
        raise ValueError(f'Symbolic links are not allowed: {target}')
    if not target.exists():
        return None
    if not target.is_file():
        raise ValueError(f'Path is not a file: {target}')
    return target.read_text(encoding='utf-8')


def _commit_pending_changes(pending: dict[Path, str | None]) -> None:
    """Write validated changes and restore original files after an I/O failure."""

    originals: dict[Path, tuple[bytes | None, int | None]] = {}
    for target in pending:
        if target.exists() and target.is_symlink():
            raise ValueError(f'Symbolic links are not allowed: {target}')
        originals[target] = (
            (target.read_bytes(), target.stat().st_mode) if target.exists() else (None, None)
        )
    try:
        for target, content in pending.items():
            if content is None:
                if target.exists():
                    target.unlink()
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding='utf-8')
    except OSError as exc:
        _restore_original_files(originals)
        raise ValueError(f'Could not apply file operations: {exc}') from exc


def _restore_original_files(originals: dict[Path, tuple[bytes | None, int | None]]) -> None:
    """Best-effort restore of files captured before an incomplete write sequence."""

    for target, (content, mode) in reversed(originals.items()):
        try:
            if content is None:
                if target.exists():
                    target.unlink()
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
            if mode is not None:
                target.chmod(mode)
        except OSError:
            continue
