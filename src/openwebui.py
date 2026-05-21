"""Async Open WebUI API client.

Endpoints used:
  GET  /api/v1/knowledge/
  POST /api/v1/files/                       (multipart upload)
  GET  /api/v1/files/{file_id}/process/status
  POST /api/v1/knowledge/{kb_id}/file/add
"""
from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass

import httpx

log = logging.getLogger(__name__)


class OpenWebUIError(RuntimeError):
    pass


class ProcessingTimeout(OpenWebUIError):
    pass


@dataclass
class KnowledgeBase:
    id: str
    name: str
    description: str | None = None


class OpenWebUIClient:
    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        *,
        timeout: float = 30.0,
    ) -> None:
        self.base_url = (base_url or os.environ["OPENWEBUI_BASE_URL"]).rstrip("/")
        self.api_key = api_key or os.environ["OPENWEBUI_API_KEY"]
        self._timeout = timeout
        self._client: httpx.AsyncClient | None = None

    @property
    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}"}

    async def __aenter__(self) -> "OpenWebUIClient":
        self._client = httpx.AsyncClient(base_url=self.base_url, timeout=self._timeout)
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    def _http(self) -> httpx.AsyncClient:
        if not self._client:
            raise RuntimeError("Use async with OpenWebUIClient(...) as client")
        return self._client

    async def _request_with_retry(
        self,
        method: str,
        path: str,
        *,
        max_attempts: int = 4,
        **kwargs,
    ) -> httpx.Response:
        delay = 1.0
        last_exc: Exception | None = None
        for attempt in range(1, max_attempts + 1):
            try:
                resp = await self._http().request(method, path, headers=self._headers, **kwargs)
                if resp.status_code >= 500:
                    raise httpx.HTTPStatusError(
                        f"server error {resp.status_code}", request=resp.request, response=resp
                    )
                return resp
            except (httpx.TransportError, httpx.HTTPStatusError) as exc:
                last_exc = exc
                if attempt == max_attempts:
                    break
                log.warning(
                    "Open WebUI %s %s failed (attempt %d/%d): %s — retrying in %.1fs",
                    method, path, attempt, max_attempts, exc, delay,
                )
                await asyncio.sleep(delay)
                delay *= 2
        raise OpenWebUIError(f"Open WebUI request failed after {max_attempts} attempts: {last_exc}")

    async def list_knowledge_bases(self) -> list[KnowledgeBase]:
        resp = await self._request_with_retry("GET", "/api/v1/knowledge/")
        if resp.status_code != 200:
            raise OpenWebUIError(f"list KBs failed: {resp.status_code} {resp.text[:200]}")
        data = resp.json()
        out: list[KnowledgeBase] = []
        for item in data:
            out.append(
                KnowledgeBase(
                    id=item["id"],
                    name=item.get("name", "(unnamed)"),
                    description=item.get("description"),
                )
            )
        return out

    async def upload_file(self, filename: str, content: bytes, content_type: str = "text/markdown") -> str:
        files = {"file": (filename, content, content_type)}
        resp = await self._request_with_retry("POST", "/api/v1/files/", files=files)
        if resp.status_code not in (200, 201):
            raise OpenWebUIError(f"upload failed: {resp.status_code} {resp.text[:200]}")
        return resp.json()["id"]

    async def wait_until_processed(self, file_id: str, *, max_seconds: int = 60) -> None:
        for _ in range(max_seconds):
            resp = await self._request_with_retry("GET", f"/api/v1/files/{file_id}/process/status")
            if resp.status_code == 200:
                status = resp.json().get("status")
                if status == "completed":
                    return
                if status == "failed":
                    raise OpenWebUIError(f"file {file_id} processing failed")
            await asyncio.sleep(1)
        raise ProcessingTimeout(f"file {file_id} not processed within {max_seconds}s")

    async def attach_to_kb(self, kb_id: str, file_id: str) -> None:
        resp = await self._request_with_retry(
            "POST",
            f"/api/v1/knowledge/{kb_id}/file/add",
            json={"file_id": file_id},
        )
        if resp.status_code not in (200, 201):
            raise OpenWebUIError(f"attach failed: {resp.status_code} {resp.text[:200]}")

    async def upload_and_attach(
        self,
        *,
        kb_id: str,
        filename: str,
        content: bytes,
        content_type: str = "text/markdown",
    ) -> str:
        file_id = await self.upload_file(filename, content, content_type)
        await self.wait_until_processed(file_id)
        await self.attach_to_kb(kb_id, file_id)
        return file_id
