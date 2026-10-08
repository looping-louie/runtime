"""HTTP client for runtime worker registration and heartbeats."""

from __future__ import annotations

from urllib.parse import quote

from clients.api_client import RuntimeApiClient


class WorkerHeartbeatClient(RuntimeApiClient):
    """Register global Workers, enable Projects, and refresh API liveness."""

    def provision(
        self,
        *,
        project_id: str,
        harnesses: tuple[str, ...],
    ) -> str:
        """Register one global Worker and return its API-generated ID."""

        response = self._request_object(
            method='POST',
            project_id=project_id,
            path='/workers',
            operation='Worker lifecycle',
            object_error='Worker lifecycle response must be a JSON object.',
            payload={
                'project_id': project_id,
                **_capability_payload(harnesses),
            },
        )
        worker_id = response.get('id')
        if not isinstance(worker_id, str) or not worker_id:
            raise RuntimeError('Global Worker registration response is missing its ID.')
        return worker_id

    def enable_project(self, *, worker_id: str, project_id: str) -> None:
        """Enable one global Worker to claim work for one Project."""

        self._request_object(
            method='POST',
            project_id=project_id,
            path=(
                f'/workers/{quote(worker_id, safe="")}/projects/'
                f'{quote(project_id, safe="")}'
            ),
            operation='Worker lifecycle',
            object_error='Worker lifecycle response must be a JSON object.',
            payload={},
        )

    def heartbeat(
        self,
        *,
        project_id: str,
        worker_id: str,
        harnesses: tuple[str, ...],
    ) -> None:
        """Record a liveness heartbeat for one registered runtime worker."""

        self._request_object(
            method='POST',
            project_id=project_id,
            path=f'/workers/{quote(worker_id, safe="")}/heartbeat',
            operation='Worker lifecycle',
            object_error='Worker lifecycle response must be a JSON object.',
            payload=_capability_payload(harnesses),
        )


def _capability_payload(harnesses: tuple[str, ...]) -> dict[str, object]:
    """Serialize detected Harness identities for worker lifecycle requests."""

    return {'harnesses': [
        {'kind': harness, 'version': 'v1', 'config': {}}
        for harness in harnesses
    ]}
