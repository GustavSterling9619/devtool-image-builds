from __future__ import annotations

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from .build_pipeline import AssetMissing, BuildEvent, BuildPipeline, ReleaseRecord, UploadRequest, UploadTicket
from .infrai_client import InfraiClient, InfraiError


def create_app(pipeline: BuildPipeline | None = None) -> FastAPI:
    app = FastAPI(title="Developer image builds", version="0.1.0")
    active_pipeline = pipeline

    def get_pipeline() -> BuildPipeline:
        nonlocal active_pipeline
        if active_pipeline is None:
            active_pipeline = BuildPipeline(InfraiClient())
        return active_pipeline

    @app.exception_handler(InfraiError)
    async def infrai_error_handler(_request: Request, exc: InfraiError) -> JSONResponse:
        status = exc.status_code if 400 <= exc.status_code < 500 else 502
        return JSONResponse(status_code=status, content={"code": exc.code, "detail": exc.detail})

    @app.post("/uploads", response_model=UploadTicket, status_code=201)
    def create_upload(
        request: UploadRequest, service: BuildPipeline = Depends(get_pipeline)
    ) -> UploadTicket:
        return service.issue_upload(request)

    @app.post("/build-events", response_model=ReleaseRecord, status_code=201)
    def submit_build(
        event: BuildEvent, service: BuildPipeline = Depends(get_pipeline)
    ) -> ReleaseRecord:
        try:
            return service.process_build(event)
        except AssetMissing as exc:
            raise HTTPException(status_code=409, detail=f"Upload {exc.asset_key} is not complete") from exc

    @app.get("/releases/{build_id}", response_model=ReleaseRecord)
    def get_release(
        build_id: str, service: BuildPipeline = Depends(get_pipeline)
    ) -> ReleaseRecord:
        release = service.get_release(build_id)
        if release is None:
            raise HTTPException(status_code=404, detail="Build has no release record")
        return release

    @app.get("/diagnostics/{build_id}")
    def get_diagnostic(build_id: str, service: BuildPipeline = Depends(get_pipeline)):
        release = service.get_release(build_id)
        if release is None:
            raise HTTPException(status_code=404, detail="Build has no diagnostic record")
        return release.diagnostic

    return app


app = create_app()
