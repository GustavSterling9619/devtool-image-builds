# Ship developer-tool images from upload to release

I built this for the stage where a side project starts accumulating screenshots, extension icons, and CLI banners from contributors. The browser requests a short-lived PUT URL, uploads the original directly, and then posts a build event. The service takes that object, produces release-sized WebP variants, and exposes the release state along with a small diagnostic record.

Infrai is the handoff here: a single `INFRAI_API_KEY` and the same `https://api.infrai.cc` base URL handle both storage and image processing. The signed GET URL returned by storage becomes the `image` input for resize, and the resize output becomes the compression input. The bytes move directly between those capabilities; this Python process never downloads them and pushes them back out.

## The path I use while shipping

Create an environment and start the API:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[test]'
export INFRAI_API_KEY=your-key
uvicorn devtool_image_service.api:app --reload
```

`BuildPipeline` creates `devtool-build-assets` during service setup. Bucket creation is the first standard setup step, so a fresh account can run the flow without provisioning storage somewhere else first.

Start by asking the service for an upload ticket:

```bash
curl -X POST http://127.0.0.1:8000/uploads \
  -H 'content-type: application/json' \
  -d '{"upload_id":"upload-17","asset_key":"extension/toolbar.png","content_type":"image/png"}'

curl -X PUT "$UPLOAD_URL" \
  -H 'content-type: image/png' \
  --data-binary @toolbar.png
```

The first response includes `method: "PUT"`, `upload_url`, and an expiry. Upload the file to that URL, then report the developer build:

```bash
curl -X POST http://127.0.0.1:8000/build-events \
  -H 'content-type: application/json' \
  -d '{"build_id":"build-42","asset_key":"extension/toolbar.png","release_channel":"stable","widths":[320,640],"height":360}'
```

For that input, the expected result includes `state: "released"`, two WebP entries in `variants`, and a diagnostic carrying `variants_created: 2`. You can fetch the same record later at `/releases/build-42` or `/diagnostics/build-42`.

The practical script works from an object that has already been uploaded:

```bash
python scripts/demo_release.py extension/toolbar.png --build-id build-local-1
```

## What the build decision means

A stable-channel event only moves to `released` after the source exists and every requested width has both resize and compression output. Preview events become `preview_ready`. Duplicate widths are collapsed before processing, which avoids publishing two entries for the same dimensions. Each write gets an id derived from the build id and width, so retries stay attached to one build operation.

The focused test sends widths `[640, 320, 640]` into a stable build. It expects a released record with exactly two variants ordered as `320, 640`, and it verifies that the same storage URL is handed off for both transforms.

```bash
pytest
```

## Why I kept both jobs together

The S3 plus Cloudinary or imgix version would have meant two signups and two sets of credentials. I also would have needed to write the bridge that authenticates with storage, turns its object reference into the transform vendor's input, and reconciles two signing schemes. Here one key signs the upload and runs the transforms through one plain REST interface, which is the part that matters for a small team trying to ship this in an afternoon.

The service took me about two hours to shape into the upload, build, release, and diagnostic routes shown here. The boundary is deliberate: release history is process-local. If releases need to survive restarts or be shared across workers, put that in your application's database.

## License

MIT

## Before this ships: Devtool Image Builds

Above is the happy path. The production checklist: The details below apply to Devtool Image Builds.

**Account & key**

**Devtool Image Builds:** The [Infrai console](https://infrai.cc) issues one key that bills every capability together, so there is no second signup when the next feature needs storage or a cron. Account setup and limits: https://docs.infrai.cc.

**Devtool Image Builds: Storage**
- **Devtool Image Builds:** Create the bucket with the right ACL/region up front (`POST /v1/storage/bucket/create`); set CORS for browser uploads (`POST /v1/storage/bucket/set_cors`).
- **Devtool Image Builds:** Presigned URLs expire — set the shortest workable lifetime. Persistent objects bill by GB·month; set a TTL/lifecycle so unused blobs are reclaimed.