from __future__ import annotations
from datetime import datetime
from typing import Optional, TypeVar, Generic, List
from pydantic import BaseModel, Field

T = TypeVar("T")

class APIResponse(BaseModel, Generic[T]):
    success: bool = True
    data: Optional[T] = None
    message: str = "OK"

class PaginatedResponse(BaseModel, Generic[T]):
    items: List[T]
    total: int
    page: int
    page_size: int
    pages: int
