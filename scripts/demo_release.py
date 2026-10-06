from __future__ import annotations

import argparse
import json

from devtool_image_service.build_pipeline import BuildEvent, BuildPipeline
from devtool_image_service.infrai_client import InfraiClient


def main() -> None:
    parser = argparse.ArgumentParser(description="Process an uploaded image into release variants")
    parser.add_argument("asset_key")
    parser.add_argument("--build-id", default="build-local-1")
    args = parser.parse_args()

    client = InfraiClient()
    try:
        pipeline = BuildPipeline(client)
        release = pipeline.process_build(
            BuildEvent(
                build_id=args.build_id,
                asset_key=args.asset_key,
                release_channel="preview",
                widths=[320, 640],
                height=360,
            )
        )
        print(json.dumps(release.model_dump(), indent=2))
    finally:
        client.close()


if __name__ == "__main__":
    main()
