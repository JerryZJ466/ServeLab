import tomllib
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from servelab.core.http import server_origin


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    backend: Literal["mock", "vllm"] = "mock"
    model: str = Field(default="servelab-mock", min_length=1, max_length=200)
    max_inflight: int = Field(default=2, ge=1, le=1024)
    max_queue: int = Field(default=8, ge=0, le=10000)
    queue_timeout: float = Field(default=2.0, gt=0, le=3600)
    request_timeout: float = Field(default=10.0, gt=0, le=3600)
    mock_token_delay: float = Field(default=0.01, ge=0, le=10)
    upstream_base_url: str = "http://127.0.0.1:8001"
    upstream_api_key_env: str | None = Field(default=None, pattern=r"^[A-Z][A-Z0-9_]*$")

    @field_validator("upstream_base_url")
    @classmethod
    def validate_origin(cls, value: str) -> str:
        return server_origin(value)

    @classmethod
    def from_file(cls, path: Path) -> "Settings":
        with path.open("rb") as source:
            return cls.model_validate(tomllib.load(source))
