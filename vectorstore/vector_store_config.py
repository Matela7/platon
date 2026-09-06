from __future__ import annotations

from pydantic import BaseModel, Field, ConfigDict
from pathlib import Path

class VectorStoreConfig(BaseModel):
    persist_dir: Path = Field(default=Path("./chroma_data"))