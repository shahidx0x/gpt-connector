from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from localcontrol.api.deps import log_success
from localcontrol.auth import require_auth
from localcontrol.models import SearchContentRequest, SearchContentResponse, SearchFilesRequest, SearchFilesResponse
from localcontrol.search_ops import search_content, search_files

router = APIRouter(tags=["search"], dependencies=[Depends(require_auth)])


@router.post("/search/files", response_model=SearchFilesResponse, operation_id="search_files")
async def search_files_endpoint(payload: SearchFilesRequest, request: Request) -> SearchFilesResponse:
    response = search_files(payload)
    log_success(request, "search.files", target=response.root, details={"count": len(response.results), "truncated": response.truncated})
    return response


@router.post("/search/content", response_model=SearchContentResponse, operation_id="search_content")
async def search_content_endpoint(payload: SearchContentRequest, request: Request) -> SearchContentResponse:
    response = search_content(payload)
    log_success(request, "search.content", target=response.root, details={"count": len(response.matches), "truncated": response.truncated})
    return response

