"""Shared authenticated HTTP transport for runtime API clients."""

from __future__ import annotations

from collections.abc import Collection

import httpx


class RuntimeApiClient:
    """Send project-scoped requests and normalize transport failures."""

    request_timeout_seconds = 60.0

    def __init__(
        self,
        *,
        api_base_url: str,
        user_id: str,
        client: httpx.Client | None = None,
    ) -> None:
        """Store API identity and optionally inject an HTTP client for tests."""

        self._api_base_url = api_base_url.rstrip('/')
        self._user_id = user_id
        self._client = client or httpx.Client(timeout=self.request_timeout_seconds)

    def _request(
        self,
        *,
        method: str,
        project_id: str,
        path: str,
        operation: str,
        payload: dict[str, object] | None = None,
        params: dict[str, str] | None = None,
        headers: dict[str, str] | None = None,
        accepted_error_statuses: Collection[int] = (),
    ) -> httpx.Response:
        """Send one request and reject unexpected transport or HTTP failures."""

        try:
            response = self._client.request(
                method,
                f'{self._api_base_url}{path}',
                params=params,
                json=payload,
                headers={
                    'X-Project-ID': project_id,
                    'X-User-ID': self._user_id,
                    **(headers or {}),
                },
            )
        except httpx.RequestError as exc:
            raise RuntimeError(f'{operation} request failed: {exc}') from exc
        if response.is_error and response.status_code not in accepted_error_statuses:
            raise RuntimeError(
                f'{operation} request returned HTTP {response.status_code}: '
                f'{response.text}'
            )
        return response

    def _request_object(
        self,
        *,
        method: str,
        project_id: str,
        path: str,
        operation: str,
        object_error: str,
        payload: dict[str, object] | None = None,
        params: dict[str, str] | None = None,
        headers: dict[str, str] | None = None,
    ) -> dict[str, object]:
        """Send one request and require a JSON object response."""

        value = self._request(
            method=method,
            project_id=project_id,
            path=path,
            operation=operation,
            payload=payload,
            params=params,
            headers=headers,
        ).json()
        if not isinstance(value, dict):
            raise RuntimeError(object_error)
        return value
