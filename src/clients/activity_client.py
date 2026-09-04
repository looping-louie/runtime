"""HTTP client for activity-run checkpoint operations."""

from __future__ import annotations

from urllib.parse import quote

from clients.api_client import RuntimeApiClient


class ActivityRunClient(RuntimeApiClient):
    """Fetch and advance Activity runs allocated to a claimed Pipeline run."""

    request_timeout_seconds = 300.0

    def get_run(
        self,
        *,
        project_id: str,
        activity_id: str,
        run_id: str,
    ) -> dict[str, object]:
        """Return one project-scoped Activity run from the API."""

        return self._request_object(
            method='GET',
            project_id=project_id,
            path=self._run_path(activity_id=activity_id, run_id=run_id),
            operation='Activity checkpoint',
            object_error='Activity checkpoint response must be a JSON object.',
        )

    def continue_run(
        self,
        *,
        project_id: str,
        activity_id: str,
        run_id: str,
        pipeline_run_id: str,
        lease_token: str,
        continuation_token: str,
        idempotency_key: str,
        result: dict[str, object],
    ) -> dict[str, object]:
        """Submit one idempotent local checkpoint result and return the next state."""

        return self._request_object(
            method='POST',
            project_id=project_id,
            path=f'{self._run_path(activity_id=activity_id, run_id=run_id)}/continue',
            operation='Activity checkpoint',
            object_error='Activity checkpoint response must be a JSON object.',
            payload={
                'pipeline_run_id': pipeline_run_id,
                'lease_token': lease_token,
                'continuation_token': continuation_token,
                'idempotency_key': idempotency_key,
                'result': result,
            },
        )

    @staticmethod
    def _run_path(*, activity_id: str, run_id: str) -> str:
        """Build the encoded API path for one Activity run."""

        return (
            f'/activities/{quote(activity_id, safe="")}/runs/'
            f'{quote(run_id, safe="")}'
        )
