"""
FindIT Hybrid Search API Router
Exposes hybrid retrieval combining dense FAISS and sparse BM25 via Reciprocal Rank Fusion.
"""

from typing import Optional
from fastapi import APIRouter, Query, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

from app.services.search_service import get_search_service, SearchResponse

router = APIRouter(tags=["Search"])


class SearchRequestBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(..., min_length=1, description="Search query string")
    limit: int = Field(default=10, ge=1, le=100, description="Max passages to return")
    offset: int = Field(default=0, ge=0, description="Pagination offset")
    include_diagnostics: bool = Field(default=False, description="Include raw retriever diagnostics")


@router.post("/search", response_model=SearchResponse)
async def search_passages_post(body: SearchRequestBody):
    """
    POST /api/search
    Executes hybrid dense + lexical search using Reciprocal Rank Fusion (k=60)
    and returns one unified backend-ranked result list.
    """
    service = get_search_service()
    try:
        response = service.search(
            query=body.query,
            limit=body.limit,
            offset=body.offset,
        )
        return response
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Search execution failed: {str(e)}",
        )


@router.get("/search", response_model=SearchResponse)
async def search_passages_get(
    q: str = Query(..., min_length=1, description="Search query string"),
    limit: int = Query(default=10, ge=1, le=100, description="Max passages to return"),
    offset: int = Query(default=0, ge=0, description="Pagination offset"),
    ranking_mode: Optional[str] = Query(default=None, include_in_schema=False),
):
    """
    GET /api/search?q=...&limit=10&offset=0
    Alternative GET endpoint for query-string-based search.
    """
    if ranking_mode is not None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Ranking modes are not supported; search is always hybrid.",
        )
    service = get_search_service()
    try:
        response = service.search(
            query=q,
            limit=limit,
            offset=offset,
        )
        return response
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Search execution failed: {str(e)}",
        )
