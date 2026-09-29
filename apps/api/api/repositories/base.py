from __future__ import annotations
from typing import Generic, TypeVar, Optional, List, Type
from sqlalchemy.orm import Session

ModelT = TypeVar("ModelT")

class BaseRepository(Generic[ModelT]):
    model: Type[ModelT]

    def __init__(self, db: Session):
        self.db = db

    def get(self, id: str) -> Optional[ModelT]:
        return self.db.get(self.model, id)

    def get_all(self, skip: int = 0, limit: int = 100) -> List[ModelT]:
        return self.db.query(self.model).offset(skip).limit(limit).all()

    def count(self) -> int:
        return self.db.query(self.model).count()

    def create(self, obj: ModelT) -> ModelT:
        self.db.add(obj)
        self.db.commit()
        self.db.refresh(obj)
        return obj

    def save(self, obj: ModelT) -> ModelT:
        self.db.commit()
        self.db.refresh(obj)
        return obj

    def delete(self, obj: ModelT) -> None:
        self.db.delete(obj)
        self.db.commit()
