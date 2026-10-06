from typing import Any

import pytest

from devtool_image_service.build_pipeline import AssetMissing, BuildEvent, BuildPipeline


class FakeBackend:
    def __init__(self, found: bool = True) -> None:
        self.found = found
        self.created_bucket = ""
        self.handoffs: list[tuple[str, int]] = []

    def create_bucket(self, name: str) -> dict[str, Any]:
        self.created_bucket = name
        return {"name": name}

    def presign_put(self, bucket: str, key: str, content_type: str, event_id: str) -> dict[str, Any]:
        return {"url": "https://upload.example/signed"}

    def head_object(self, bucket: str, key: str) -> dict[str, Any]:
        return {"found": self.found}

    def presign_get(self, bucket: str, key: str, event_id: str) -> dict[str, Any]:
        return {"url": "https://download.example/source"}

    def resize_image(self, image_url: str, width: int, height: int, event_id: str) -> dict[str, Any]:
        self.handoffs.append((image_url, width))
        return {"image_id": f"resized-{width}"}

    def compress_image(self, image_id: str, event_id: str) -> dict[str, Any]:
        final_id = f"compressed-{image_id}"
        return {"image_id": final_id, "url": f"https://images.example/{final_id}.webp"}


def test_stable_build_releases_sorted_unique_variants() -> None:
    backend = FakeBackend()
    pipeline = BuildPipeline(backend)

    release = pipeline.process_build(
        BuildEvent(
            build_id="build-42",
            asset_key="extension/toolbar.png",
            release_channel="stable",
            widths=[640, 320, 640],
            height=360,
        )
    )

    assert release.state == "released"
    assert [item.width for item in release.variants] == [320, 640]
    assert release.diagnostic.variants_created == 2
    assert backend.handoffs == [
        ("https://download.example/source", 320),
        ("https://download.example/source", 640),
    ]


def test_build_waits_until_upload_is_present() -> None:
    pipeline = BuildPipeline(FakeBackend(found=False))

    with pytest.raises(AssetMissing):
        pipeline.process_build(
            BuildEvent(
                build_id="build-43",
                asset_key="cli/banner.png",
                release_channel="preview",
                widths=[320],
                height=180,
            )
        )
