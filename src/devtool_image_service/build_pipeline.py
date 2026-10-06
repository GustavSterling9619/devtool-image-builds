from __future__ import annotations

from dataclasses import asdict, dataclass
import re
from typing import Any, Protocol


class DataModel:
    def model_dump(self) -> dict[str, Any]:
        return asdict(self)  # type: ignore[arg-type]


@dataclass
class UploadRequest(DataModel):
    asset_key: str
    content_type: str
    upload_id: str

    def __post_init__(self) -> None:
        if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]*", self.asset_key) is None:
            raise ValueError("asset_key has an invalid format")
        if re.fullmatch(r"image/(png|jpeg|webp)", self.content_type) is None:
            raise ValueError("content_type must be image/png, image/jpeg, or image/webp")
        if len(self.upload_id) < 3:
            raise ValueError("upload_id must contain at least 3 characters")


@dataclass
class UploadTicket(DataModel):
    upload_id: str
    asset_key: str
    method: str
    upload_url: str
    expires_seconds: int


@dataclass
class BuildEvent(DataModel):
    build_id: str
    asset_key: str
    release_channel: str
    widths: list[int]
    height: int

    def __post_init__(self) -> None:
        if len(self.build_id) < 3:
            raise ValueError("build_id must contain at least 3 characters")
        if not self.asset_key:
            raise ValueError("asset_key must not be empty")
        if self.release_channel not in {"preview", "stable"}:
            raise ValueError("release_channel must be preview or stable")
        if not 1 <= len(self.widths) <= 5:
            raise ValueError("widths must contain between 1 and 5 items")
        if not 0 < self.height <= 4096:
            raise ValueError("height must be between 1 and 4096")


@dataclass
class Variant(DataModel):
    width: int
    height: int
    image_id: str
    url: str
    format: str = "webp"


@dataclass
class BuildDiagnostic(DataModel):
    build_id: str
    state: str
    message: str
    variants_created: int


@dataclass
class ReleaseRecord(DataModel):
    build_id: str
    release_channel: str
    state: str
    variants: list[Variant]
    diagnostic: BuildDiagnostic


class ImageBackend(Protocol):
    def create_bucket(self, name: str) -> dict[str, Any]:
        raise RuntimeError("protocol method called")

    def presign_put(self, bucket: str, key: str, content_type: str, event_id: str) -> dict[str, Any]:
        raise RuntimeError("protocol method called")

    def head_object(self, bucket: str, key: str) -> dict[str, Any]:
        raise RuntimeError("protocol method called")

    def presign_get(self, bucket: str, key: str, event_id: str) -> dict[str, Any]:
        raise RuntimeError("protocol method called")

    def resize_image(self, image_url: str, width: int, height: int, event_id: str) -> dict[str, Any]:
        raise RuntimeError("protocol method called")

    def compress_image(self, image_id: str, event_id: str) -> dict[str, Any]:
        raise RuntimeError("protocol method called")


@dataclass
class AssetMissing(Exception):
    asset_key: str


class BuildPipeline:
    def __init__(self, backend: ImageBackend, bucket: str = "devtool-build-assets") -> None:
        self.backend = backend
        self.bucket = bucket
        self.releases: dict[str, ReleaseRecord] = {}

    def issue_upload(self, request: UploadRequest) -> UploadTicket:
        signed = self.backend.presign_put(
            self.bucket, request.asset_key, request.content_type, request.upload_id
        )
        return UploadTicket(
            upload_id=request.upload_id,
            asset_key=request.asset_key,
            method="PUT",
            upload_url=str(signed["url"]),
            expires_seconds=600,
        )

    def process_build(self, event: BuildEvent) -> ReleaseRecord:
        source = self.backend.head_object(self.bucket, event.asset_key)
        if not source.get("found", False):
            raise AssetMissing(event.asset_key)

        download = self.backend.presign_get(
            self.bucket, event.asset_key, f"{event.build_id}-source"
        )
        variants: list[Variant] = []
        for width in sorted(set(event.widths)):
            resized = self.backend.resize_image(
                str(download["url"]), width, event.height, f"{event.build_id}-{width}-resize"
            )
            compressed = self.backend.compress_image(
                str(resized["image_id"]), f"{event.build_id}-{width}-compress"
            )
            variants.append(
                Variant(
                    width=width,
                    height=event.height,
                    image_id=str(compressed["image_id"]),
                    url=str(compressed["url"]),
                )
            )

        state = "released" if event.release_channel == "stable" else "preview_ready"
        release = ReleaseRecord(
            build_id=event.build_id,
            release_channel=event.release_channel,
            state=state,
            variants=variants,
            diagnostic=BuildDiagnostic(
                build_id=event.build_id,
                state="healthy",
                message=f"Created {len(variants)} WebP variants",
                variants_created=len(variants),
            ),
        )
        self.releases[event.build_id] = release
        return release

    def get_release(self, build_id: str) -> ReleaseRecord | None:
        return self.releases.get(build_id)
