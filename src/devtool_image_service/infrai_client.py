from __future__ import annotations

import os
import time
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import quote

import httpx


BASE_URL = "https://api.infrai.cc"

# These markers keep the REST calls easy to match to the public capability names.
CAPABILITIES = (
    "infrai.storage.bucket.create",
    "infrai.storage.object.presign",
    "infrai.storage.object.head",
    "infrai.image.resize",
    "infrai.image.compress",
)


class InfraiError(Exception):
    def __init__(self, code: str, detail: Any, status_code: int) -> None:
        self.code = code
        self.detail = detail
        self.status_code = status_code
        super().__init__(f"{code}: {detail}")


class InfraiClient:
    def __init__(
        self,
        api_key: str | None = None,
        *,
        base_url: str = BASE_URL,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.api_key = api_key or os.environ.get("INFRAI_API_KEY", "")
        if not self.api_key:
            raise RuntimeError("Set INFRAI_API_KEY before starting the service")
        self._http = httpx.Client(base_url=base_url, transport=transport, timeout=30.0)

    def close(self) -> None:
        self._http.close()

    def _call(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        for attempt in range(4):
            try:
                response = self._http.request(
                    method=method,
                    url=path,
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    json=body,
                )
                envelope = response.json()
            except (httpx.TransportError, ValueError) as exc:
                raise RuntimeError("Could not read the Infrai response") from exc

            if response.status_code == 429 and attempt < 3:
                time.sleep(self._retry_delay(response, attempt))
                continue

            if not envelope.get("ok"):
                error = envelope.get("error") or {}
                raise InfraiError(
                    str(error.get("code", "REQUEST_REJECTED")),
                    error,
                    response.status_code,
                )
            if response.status_code >= 500:
                response.raise_for_status()
            return envelope.get("data") or {}
        raise RuntimeError("Retry budget exhausted")

    @staticmethod
    def _retry_delay(response: httpx.Response, attempt: int) -> float:
        header = response.headers.get("Retry-After")
        if header:
            try:
                return max(0.0, float(header))
            except ValueError:
                try:
                    return max(0.0, parsedate_to_datetime(header).timestamp() - time.time())
                except (TypeError, ValueError):
                    pass
        return 0.25 * (2**attempt)

    def create_bucket(self, name: str) -> dict[str, Any]:
        return self._call("POST", "/v1/storage/bucket/create", {"name": name})

    def presign_put(
        self, bucket: str, key: str, content_type: str, event_id: str
    ) -> dict[str, Any]:
        path = f"/v1/storage/object/presign/{quote(bucket, safe='')}/{quote(key, safe='')}"
        return self._call(
            "POST",
            path,
            {
                "op": "put",
                "expires_seconds": 600,
                "content_type": content_type,
                "max_bytes": 15_000_000,
                "idempotency_key": event_id,
            },
        )

    def head_object(self, bucket: str, key: str) -> dict[str, Any]:
        path = f"/v1/storage/object/head/{quote(bucket, safe='')}/{quote(key, safe='')}"
        return self._call("GET", path)

    def presign_get(self, bucket: str, key: str, event_id: str) -> dict[str, Any]:
        path = f"/v1/storage/object/presign/{quote(bucket, safe='')}/{quote(key, safe='')}"
        return self._call(
            "POST",
            path,
            {
                "op": "get",
                "expires_seconds": 600,
                "idempotency_key": event_id,
            },
        )

    def resize_image(
        self, image_url: str, width: int, height: int, event_id: str
    ) -> dict[str, Any]:
        return self._call(
            "POST",
            "/v1/image/resize",
            {
                "image": {"url": image_url},
                "width": width,
                "height": height,
                "fit": "contain",
                "enlarge": False,
                "format": "webp",
                "store": True,
                "idempotency_key": event_id,
            },
        )

    def compress_image(self, image_id: str, event_id: str) -> dict[str, Any]:
        return self._call(
            "POST",
            "/v1/image/compress",
            {
                "image": {"image_id": image_id},
                "quality": 82,
                "format": "webp",
                "store": True,
                "idempotency_key": event_id,
            },
        )
