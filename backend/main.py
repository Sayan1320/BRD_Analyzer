"""
FastAPI backend — GCP MCP Server endpoints + Requirement Summarizer.
"""

from __future__ import annotations

import dataclasses
import os
import time
from contextlib import asynccontextmanager
from typing import Any, Optional

from fastapi import Depends, FastAPI, File, HTTPException, UploadFile
from starlette.middleware.base import BaseHTTPMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from logging_config import configure_logging, get_logger
from gcp_mcp_client import GCPMCPClient, MCPConnectionError, MCPToolError
from rate_limiter import limiter
from requirement_summarizer_helpers import (
    SUPPORTED_EXTENSIONS as _SUPPORTED_EXTENSIONS,
    MAX_FILE_SIZE as _MAX_FILE_SIZE,
    REQUIRED_ENV_VARS as _REQUIRED_ENV_VARS,
    validate_extension,
    validate_env_vars,
)

logger = get_logger(__name__)


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.url.path == "/health":
            return await call_next(request)

        start = time.perf_counter()
        response = await call_next(request)
        duration_ms = round((time.perf_counter() - start) * 1000, 2)

        client_ip = request.client.host if request.client else None
        user_agent = request.headers.get("user-agent")

        logger.info(
            "http_request",
            method=request.method,
            path=request.url.path,
            client_ip=client_ip,
            user_agent=user_agent,
            status_code=response.status_code,
            duration_ms=duration_ms,
        )
        return response


# ---------------------------------------------------------------------------
# Module-level GCP MCP client
# ---------------------------------------------------------------------------

try:
    gcp_client = GCPMCPClient()
except Exception:
    gcp_client = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()

    # Validate all required env vars for the requirement summarizer
    validate_env_vars()

    # Initialize the database
    from database import init_db
    await init_db()

    await gcp_client.connect() if gcp_client else None
    try:
        yield
    finally:
        await gcp_client.close() if gcp_client else None


app = FastAPI(lifespan=lifespan)

app.state.limiter = limiter
app.add_middleware(SlowAPIMiddleware)
app.add_middleware(RequestLoggingMiddleware)


@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request: Request, exc: RateLimitExceeded):
    retry_after = int(exc.retry_after) if hasattr(exc, "retry_after") else 60
    return JSONResponse(
        status_code=429,
        content={
            "error": "rate_limit_exceeded",
            "message": "Rate limit exceeded. Please wait.",
            "retry_after_seconds": retry_after,
        },
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _call(tool_name: str, arguments: dict) -> dict[str, Any]:
    if gcp_client is None:
        raise HTTPException(status_code=503, detail="GCP MCP server not configured")
    try:
        result = await gcp_client.call_tool(tool_name, arguments)
        return {"status": "ok", "output": result.content}
    except MCPToolError as e:
        raise HTTPException(status_code=502, detail=e.message)
    except MCPConnectionError as e:
        raise HTTPException(status_code=503, detail=str(e))


# ---------------------------------------------------------------------------
# Cloud Run — request models
# ---------------------------------------------------------------------------

class CloudRunDeployRequest(BaseModel):
    service_name: str
    image: str
    region: str


class CloudRunUpdateRequest(BaseModel):
    service_name: str
    region: str
    image: Optional[str] = None
    env_vars: Optional[dict] = None
    resources: Optional[dict] = None


class CloudRunDeleteRequest(BaseModel):
    service_name: str
    region: str


# ---------------------------------------------------------------------------
# Cloud Run — endpoints
# ---------------------------------------------------------------------------

@app.post("/gcp/cloudrun/deploy")
@limiter.limit("20/minute")
async def cloudrun_deploy(request: Request, req: CloudRunDeployRequest):
    return await _call("cloudrun_deploy", req.model_dump(exclude_none=True))


@app.put("/gcp/cloudrun/update")
@limiter.limit("20/minute")
async def cloudrun_update(request: Request, req: CloudRunUpdateRequest):
    return await _call("cloudrun_update", req.model_dump(exclude_none=True))


@app.get("/gcp/cloudrun/list")
@limiter.limit("20/minute")
async def cloudrun_list(request: Request, region: Optional[str] = None):
    args: dict[str, Any] = {}
    if region is not None:
        args["region"] = region
    return await _call("cloudrun_list", args)


@app.get("/gcp/cloudrun/describe")
@limiter.limit("20/minute")
async def cloudrun_describe(request: Request, service_name: str, region: str):
    return await _call("cloudrun_describe", {"service_name": service_name, "region": region})


@app.delete("/gcp/cloudrun/delete")
@limiter.limit("20/minute")
async def cloudrun_delete(request: Request, req: CloudRunDeleteRequest):
    return await _call("cloudrun_delete", req.model_dump(exclude_none=True))


# ---------------------------------------------------------------------------
# AlloyDB — request models
# ---------------------------------------------------------------------------

class AlloyDBCreateClusterRequest(BaseModel):
    cluster_id: str
    region: str
    password: str


class AlloyDBCreateInstanceRequest(BaseModel):
    cluster_id: str
    instance_id: str
    region: str
    cpu_count: int


class AlloyDBDescribeClusterRequest(BaseModel):
    cluster_id: str
    region: str


class AlloyDBDeleteClusterRequest(BaseModel):
    cluster_id: str
    region: str


# ---------------------------------------------------------------------------
# AlloyDB — endpoints
# ---------------------------------------------------------------------------

@app.post("/gcp/alloydb/create-cluster")
@limiter.limit("20/minute")
async def alloydb_create_cluster(request: Request, req: AlloyDBCreateClusterRequest):
    return await _call("alloydb_create_cluster", req.model_dump())


@app.post("/gcp/alloydb/create-instance")
@limiter.limit("20/minute")
async def alloydb_create_instance(request: Request, req: AlloyDBCreateInstanceRequest):
    return await _call("alloydb_create_instance", req.model_dump())


@app.get("/gcp/alloydb/list-clusters")
@limiter.limit("20/minute")
async def alloydb_list_clusters(request: Request):
    return await _call("alloydb_list_clusters", {})


@app.get("/gcp/alloydb/describe-cluster")
@limiter.limit("20/minute")
async def alloydb_describe_cluster(request: Request, cluster_id: str, region: str):
    return await _call("alloydb_describe_cluster", {"cluster_id": cluster_id, "region": region})


@app.delete("/gcp/alloydb/delete-cluster")
@limiter.limit("20/minute")
async def alloydb_delete_cluster(request: Request, req: AlloyDBDeleteClusterRequest):
    return await _call("alloydb_delete_cluster", req.model_dump())


# ---------------------------------------------------------------------------
# Cloud Storage — request models
# ---------------------------------------------------------------------------

class GCSCreateBucketRequest(BaseModel):
    bucket_name: str
    region: str
    storage_class: Optional[str] = None


class GCSUploadObjectRequest(BaseModel):
    bucket_name: str
    object_path: str
    content: str


class GCSDeleteObjectRequest(BaseModel):
    bucket_name: str
    object_path: str


class GCSDeleteBucketRequest(BaseModel):
    bucket_name: str


# ---------------------------------------------------------------------------
# Cloud Storage — endpoints
# ---------------------------------------------------------------------------

@app.post("/gcp/gcs/create-bucket")
@limiter.limit("20/minute")
async def gcs_create_bucket(request: Request, req: GCSCreateBucketRequest):
    return await _call("gcs_create_bucket", req.model_dump(exclude_none=True))


@app.get("/gcp/gcs/list-buckets")
@limiter.limit("20/minute")
async def gcs_list_buckets(request: Request):
    return await _call("gcs_list_buckets", {})


@app.post("/gcp/gcs/upload-object")
@limiter.limit("20/minute")
async def gcs_upload_object(request: Request, req: GCSUploadObjectRequest):
    return await _call("gcs_upload_object", req.model_dump())


@app.get("/gcp/gcs/list-objects")
@limiter.limit("20/minute")
async def gcs_list_objects(request: Request, bucket_name: str, prefix: Optional[str] = None):
    args: dict[str, Any] = {"bucket_name": bucket_name}
    if prefix is not None:
        args["prefix"] = prefix
    return await _call("gcs_list_objects", args)


@app.delete("/gcp/gcs/delete-object")
@limiter.limit("20/minute")
async def gcs_delete_object(request: Request, req: GCSDeleteObjectRequest):
    return await _call("gcs_delete_object", req.model_dump())


@app.delete("/gcp/gcs/delete-bucket")
@limiter.limit("20/minute")
async def gcs_delete_bucket(request: Request, req: GCSDeleteBucketRequest):
    return await _call("gcs_delete_bucket", req.model_dump())


# ---------------------------------------------------------------------------
# Secret Manager — request models
# ---------------------------------------------------------------------------

class SecretManagerCreateRequest(BaseModel):
    secret_id: str
    value: str


class SecretManagerAddVersionRequest(BaseModel):
    secret_id: str
    value: str


class SecretManagerDeleteRequest(BaseModel):
    secret_id: str


# ---------------------------------------------------------------------------
# Secret Manager — endpoints
# ---------------------------------------------------------------------------

@app.post("/gcp/secrets/create")
@limiter.limit("20/minute")
async def secretmanager_create(request: Request, req: SecretManagerCreateRequest):
    return await _call("secretmanager_create", req.model_dump())


@app.post("/gcp/secrets/add-version")
@limiter.limit("20/minute")
async def secretmanager_add_version(request: Request, req: SecretManagerAddVersionRequest):
    return await _call("secretmanager_add_version", req.model_dump())


@app.get("/gcp/secrets/access")
@limiter.limit("20/minute")
async def secretmanager_access(request: Request, secret_id: str):
    return await _call("secretmanager_access", {"secret_id": secret_id})


@app.get("/gcp/secrets/list")
@limiter.limit("20/minute")
async def secretmanager_list(request: Request):
    return await _call("secretmanager_list", {})


@app.delete("/gcp/secrets/delete")
@limiter.limit("20/minute")
async def secretmanager_delete(request: Request, req: SecretManagerDeleteRequest):
    return await _call("secretmanager_delete", req.model_dump())


# ---------------------------------------------------------------------------
# Artifact Registry — request models
# ---------------------------------------------------------------------------

class ArtifactRegistryCreateRepoRequest(BaseModel):
    repo_name: str
    region: str


class ArtifactRegistryListImagesRequest(BaseModel):
    repo_name: str
    region: str


class ArtifactRegistryDeleteImageRequest(BaseModel):
    image_path: str


# ---------------------------------------------------------------------------
# Artifact Registry — endpoints
# ---------------------------------------------------------------------------

@app.post("/gcp/artifactregistry/create-repo")
@limiter.limit("20/minute")
async def artifactregistry_create_repo(request: Request, req: ArtifactRegistryCreateRepoRequest):
    return await _call("artifactregistry_create_repo", req.model_dump())


@app.get("/gcp/artifactregistry/list-repos")
@limiter.limit("20/minute")
async def artifactregistry_list_repos(request: Request, region: Optional[str] = None):
    args: dict[str, Any] = {}
    if region is not None:
        args["region"] = region
    return await _call("artifactregistry_list_repos", args)


@app.get("/gcp/artifactregistry/list-images")
@limiter.limit("20/minute")
async def artifactregistry_list_images(request: Request, repo_name: str, region: str):
    return await _call("artifactregistry_list_images", {"repo_name": repo_name, "region": region})


@app.delete("/gcp/artifactregistry/delete-image")
@limiter.limit("20/minute")
async def artifactregistry_delete_image(request: Request, req: ArtifactRegistryDeleteImageRequest):
    return await _call("artifactregistry_delete_image", req.model_dump())


# ---------------------------------------------------------------------------
# IAM — request models
# ---------------------------------------------------------------------------

class IAMCreateServiceAccountRequest(BaseModel):
    account_id: str
    display_name: str


class IAMBindRoleRequest(BaseModel):
    member: str
    role: str
    resource: Optional[str] = None


class IAMGetPolicyRequest(BaseModel):
    resource: str


class IAMCreateKeyRequest(BaseModel):
    service_account_email: str


# ---------------------------------------------------------------------------
# IAM — endpoints
# ---------------------------------------------------------------------------

@app.post("/gcp/iam/create-service-account")
@limiter.limit("20/minute")
async def iam_create_service_account(request: Request, req: IAMCreateServiceAccountRequest):
    return await _call("iam_create_service_account", req.model_dump())


@app.get("/gcp/iam/list-service-accounts")
@limiter.limit("20/minute")
async def iam_list_service_accounts(request: Request):
    return await _call("iam_list_service_accounts", {})


@app.post("/gcp/iam/bind-role")
@limiter.limit("20/minute")
async def iam_bind_role(request: Request, req: IAMBindRoleRequest):
    return await _call("iam_bind_role", req.model_dump(exclude_none=True))


@app.get("/gcp/iam/get-policy")
@limiter.limit("20/minute")
async def iam_get_policy(request: Request, resource: str):
    return await _call("iam_get_policy", {"resource": resource})


@app.post("/gcp/iam/create-key")
@limiter.limit("20/minute")
async def iam_create_key(request: Request, req: IAMCreateKeyRequest):
    return await _call("iam_create_key", req.model_dump())


# ---------------------------------------------------------------------------
# API Management — request models
# ---------------------------------------------------------------------------

class APIsEnableRequest(BaseModel):
    api_name: str


class APIsDisableRequest(BaseModel):
    api_name: str


# ---------------------------------------------------------------------------
# API Management — endpoints
# ---------------------------------------------------------------------------

@app.post("/gcp/apis/enable")
@limiter.limit("20/minute")
async def apis_enable(request: Request, req: APIsEnableRequest):
    return await _call("apis_enable", req.model_dump())


@app.post("/gcp/apis/disable")
@limiter.limit("20/minute")
async def apis_disable(request: Request, req: APIsDisableRequest):
    return await _call("apis_disable", req.model_dump())


@app.get("/gcp/apis/list")
@limiter.limit("20/minute")
async def apis_list(request: Request):
    return await _call("apis_list", {})


# ===========================================================================
# Requirement Summarizer — mount the standalone app
# ===========================================================================
#
# Two-App Architecture
# --------------------
# This application uses two FastAPI instances:
#
#   Root_App  (app)   — defined in this file (main.py), served by Cloud Run.
#                       Owns all GCP MCP endpoints under /gcp/**.
#
#   Summarizer_App (rs_app) — defined in requirement_summarizer_app.py.
#                             Owns the summarizer endpoints:
#                               POST /analyze
#                               POST /voice-summary
#                               POST /voice-story
#                               GET  /history
#                               GET  /health
#
# Routing structure:
#
#   Cloud Run → main.py (Root_App)
#                 ├── /gcp/**          (GCP MCP endpoints — handled by Root_App)
#                 └── /                (mounted Summarizer_App)
#                       ├── /analyze
#                       ├── /voice-summary
#                       ├── /voice-story
#                       ├── /history
#                       └── /health
#
# The `app.mount("/", rs_app)` call below delegates all requests that do not
# match a Root_App route to the Summarizer_App.  This must remain the LAST
# statement in this file so that GCP routes registered above take precedence.
# ===========================================================================

from database import get_metrics_summary, get_session  # noqa: E402
from requirement_summarizer_app import rs_app  # noqa: E402


# ---------------------------------------------------------------------------
# Metrics — GET /metrics (Req 8.6)
# ---------------------------------------------------------------------------

@app.get("/metrics")
async def metrics(db: AsyncSession = Depends(get_session)):
    result = await get_metrics_summary(db)
    return JSONResponse(result)


app.mount("/", rs_app)
