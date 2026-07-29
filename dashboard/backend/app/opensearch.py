from __future__ import annotations

from typing import Any

import httpx


class OpenSearchError(RuntimeError):
    pass


class OpenSearchClient:
    def __init__(self, base_url: str, timeout_seconds: float = 20) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout_seconds

    async def search(
        self,
        index: str,
        body: dict[str, Any],
        *,
        allow_missing: bool = False,
    ) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(
                    f"{self._base_url}/{index}/_search",
                    params={
                        "allow_no_indices": str(allow_missing).lower(),
                        "ignore_unavailable": str(allow_missing).lower(),
                    },
                    json=body,
                )
        except httpx.HTTPError as exc:
            raise OpenSearchError(f"OpenSearch ist nicht erreichbar: {exc}") from exc

        if allow_missing and response.status_code == 404:
            return {"hits": {"total": {"value": 0}}, "aggregations": {}}
        if response.is_error:
            detail = response.text[:500]
            raise OpenSearchError(
                f"OpenSearch-Abfrage fehlgeschlagen ({response.status_code}): {detail}"
            )
        return response.json()

    async def health(self) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.get(f"{self._base_url}/_cluster/health")
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise OpenSearchError(f"OpenSearch ist nicht erreichbar: {exc}") from exc
        return response.json()
