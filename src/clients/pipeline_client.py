"""HTTP client for discovering and conditionally claiming Pipeline runs."""

from __future__ import annotations

from urllib.parse import quote

import httpx

from clients.api_client import RuntimeApiClient
from runs.models import ClaimedPipelineRun


class PipelineRunClaimClient(RuntimeApiClient):
    """Claim queued Pipeline runs for configured runtime projects."""

    def claim_next(
        self,
        *,
        project_id: str,
        worker_id: str,
    ) -> ClaimedPipelineRun | None:
        """Claim one candidate run or return None when no work is available."""

        for pipeline_id in self._active_pipeline_ids(project_id=project_id):
            for candidate in self._claimable_runs(
                project_id=project_id,
                pipeline_id=pipeline_id,
            ):
                claim = self._claim_candidate(
                    project_id=project_id,
                    pipeline_id=pipeline_id,
                    candidate=candidate,
                    worker_id=worker_id,
                )
                if claim is not None:
                    return claim
        return None

    def _active_pipeline_ids(self, *, project_id: str) -> list[str]:
        """Return every active Pipeline ID visible in the selected project."""

        value = self._request_object(
            method='GET', project_id=project_id, path='/pipelines',
            params={'status': 'active'}, operation='Pipeline list',
            object_error='Pipeline list response must contain an items array.',
        )
        if not isinstance(value.get('items'), list):
            raise RuntimeError('Pipeline list response must contain an items array.')
        return [_require_text(item, 'id') for item in value['items'] if isinstance(item, dict)]

    def _claimable_runs(
        self,
        *,
        project_id: str,
        pipeline_id: str,
    ) -> list[dict[str, object]]:
        """Return the API-approved claim candidates for one Pipeline."""

        encoded_pipeline_id = quote(pipeline_id, safe='')
        value = self._request_object(
            method='GET', project_id=project_id,
            path=f'/pipelines/{encoded_pipeline_id}/runs',
            params={'claimable': 'true'}, operation='Claimable-run list',
            object_error='Claimable-run list response must contain an items array.',
        )
        if not isinstance(value.get('items'), list):
            raise RuntimeError('Claimable-run list response must contain an items array.')
        return [item for item in value['items'] if isinstance(item, dict)]

    def _claim_candidate(
        self,
        *,
        project_id: str,
        pipeline_id: str,
        candidate: dict[str, object],
        worker_id: str,
    ) -> ClaimedPipelineRun | None:
        """Claim one listed candidate, returning None when another worker won."""

        run = candidate.get('run')
        etag = candidate.get('etag')
        if not isinstance(run, dict):
            raise RuntimeError('Claimable-run candidate is missing its run object.')
        if not isinstance(etag, str) or not etag:
            raise RuntimeError('Claimable-run candidate is missing its ETag.')
        run_id = _require_text(run, 'id')
        response = self._request(
            method='PATCH', project_id=project_id,
            path=f'/pipelines/{quote(pipeline_id, safe="")}/runs/{quote(run_id, safe="")}',
            operation='Runtime claim',
            payload={'worker_id': worker_id, 'status': 'claimed'},
            headers={'If-Match': etag},
            accepted_error_statuses=(httpx.codes.PRECONDITION_FAILED,),
        )
        if response.status_code == httpx.codes.PRECONDITION_FAILED:
            return None
        return self._to_claim(response.json(), project_id=project_id)

    def continue_run(
        self,
        *,
        project_id: str,
        pipeline_id: str,
        run_id: str,
        lease_token: str,
    ) -> dict[str, object]:
        """Advance a terminal child and return the pipeline's scheduler state."""

        return self._request_object(
            method='POST', project_id=project_id,
            path=f'/pipelines/{quote(pipeline_id, safe="")}/runs/'
            f'{quote(run_id, safe="")}/continue',
            operation='Pipeline continuation',
            object_error='Pipeline continuation response must be a JSON object.',
            payload={'lease_token': lease_token},
        )

    def renew_lease(
        self,
        *,
        project_id: str,
        pipeline_id: str,
        run_id: str,
        lease_token: str,
    ) -> None:
        """Extend the active claim lease before a runtime-owned mutation."""

        value = self._request_object(
            method='POST', project_id=project_id,
            path=f'/pipelines/{quote(pipeline_id, safe="")}/runs/'
            f'{quote(run_id, safe="")}/lease',
            operation='Pipeline lease renewal',
            object_error='Pipeline lease renewal response is missing lease_expires_at.',
            payload={'lease_token': lease_token},
        )
        if not isinstance(value.get('lease_expires_at'), str):
            raise RuntimeError('Pipeline lease renewal response is missing lease_expires_at.')

    @staticmethod
    def _to_claim(value: object, *, project_id: str) -> ClaimedPipelineRun | None:
        """Validate and map one successful API claim response."""

        if not isinstance(value, dict):
            raise RuntimeError('Runtime claim response must be a JSON object.')
        run = value.get('run')
        lease_token = value.get('lease_token')
        if not isinstance(run, dict):
            raise RuntimeError('Runtime claim response is missing the run object.')
        if run.get('status') == 'waiting':
            return None
        if not isinstance(lease_token, str) or not lease_token:
            raise RuntimeError('Runtime claim response is missing a lease token.')
        pipeline_id = _require_text(run, 'pipeline_id')
        run_id = _require_text(run, 'id')
        return ClaimedPipelineRun(
            project_id=project_id, pipeline_id=pipeline_id,
            run_id=run_id,
            lease_token=lease_token,
            payload=run,
        )


def _require_text(value: dict[str, object], field_name: str) -> str:
    """Return a required non-empty string from one API response object."""

    field_value = value.get(field_name)
    if not isinstance(field_value, str) or not field_value:
        raise RuntimeError(f'Runtime claim response is missing {field_name}.')
    return field_value
