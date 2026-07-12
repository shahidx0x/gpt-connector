from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from localcontrol.api.deps import log_success
from localcontrol.auth import require_auth
from localcontrol.models import ProjectInfo, ProjectListResponse, ProjectRegisterRequest
from localcontrol.project_ops import project_store

router = APIRouter(tags=["projects"], dependencies=[Depends(require_auth)])


@router.post("/projects/register", response_model=ProjectInfo, operation_id="project_register")
async def project_register(payload: ProjectRegisterRequest, request: Request) -> ProjectInfo:
    response = project_store.register(payload)
    log_success(request, "project.register", target=response.path, details={"project_id": response.project_id, "name": response.name})
    return response


@router.post("/projects/list", response_model=ProjectListResponse, operation_id="project_list")
async def project_list(request: Request) -> ProjectListResponse:
    response = project_store.list()
    log_success(request, "project.list", details={"count": len(response.projects)})
    return response


@router.get("/projects/{project_id}", response_model=ProjectInfo, operation_id="project_get")
async def project_get(project_id: str, request: Request) -> ProjectInfo:
    response = project_store.get(project_id)
    log_success(request, "project.get", target=response.path, details={"project_id": response.project_id, "exists": response.exists})
    return response

