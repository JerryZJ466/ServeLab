import tomllib
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from servelab.core.http import server_origin


class BenchmarkConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, strict=True)

    base_url: str = "http://127.0.0.1:8000"
    model: str = Field(default="servelab-mock", min_length=1, max_length=200)
    concurrency: list[int] = Field(default_factory=lambda: [1, 4, 8], min_length=1)
    repeats: int = Field(default=3, ge=1, le=100)
    requests_per_run: int = Field(default=24, ge=1, le=100000)
    warmup_requests: int = Field(default=2, ge=0, le=10000)
    request_timeout: float = Field(default=30, gt=0, le=3600)
    max_tokens: int = Field(default=32, ge=1, le=1024)
    temperature: float = Field(default=0, ge=0, le=2)
    stream: bool = True
    prompts: list[str] = Field(
        default_factory=lambda: ["Explain a queue in one sentence."], min_length=1, max_length=10000
    )

    @field_validator("base_url")
    @classmethod
    def validate_origin(cls, value):
        return server_origin(value)

    @field_validator("concurrency")
    @classmethod
    def validate_concurrency(cls, values):
        if len(set(values)) != len(values) or any(not 1 <= value <= 1024 for value in values):
            raise ValueError("concurrency must contain unique values in 1..1024")
        return values

    @field_validator("prompts")
    @classmethod
    def validate_prompts(cls, values):
        if any(not value.strip() or len(value) > 16384 for value in values):
            raise ValueError("prompts must contain 1..16384 characters")
        return values

    @model_validator(mode="after")
    def enough_samples(self):
        if self.requests_per_run < max(self.concurrency):
            raise ValueError("requests_per_run must be at least the largest concurrency")
        return self

    @classmethod
    def from_file(cls, path: Path):
        with path.open("rb") as source:
            return cls.model_validate(tomllib.load(source))


class RequestRow(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, strict=True)

    schema_version: Literal[1] = 1
    run_id: str
    group_id: str
    sample_id: str
    phase: Literal["warmup", "measured"]
    concurrency: int = Field(ge=1)
    repeat: int = Field(ge=1)
    prompt_index: int = Field(ge=0)
    request_id: str | None = None
    backend: str
    stream: bool
    client_arrival_at: float
    client_first_token_at: float | None = None
    client_completed_at: float
    e2e_seconds: float = Field(ge=0)
    ttft_seconds: float | None = Field(default=None, ge=0)
    tpot_seconds: float | None = Field(default=None, ge=0)
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    terminal_state: Literal["COMPLETED", "REJECTED", "FAILED", "TIMED_OUT", "CANCELLED"]
    status_code: int | None = None
    error_category: str | None = None

    @model_validator(mode="after")
    def coherent_observations(self):
        if self.client_completed_at < self.client_arrival_at:
            raise ValueError("completion precedes arrival")
        if self.ttft_seconds is not None and (
            not self.stream or self.ttft_seconds > self.e2e_seconds
        ):
            raise ValueError("invalid first-text timing")
        if self.terminal_state == "COMPLETED":
            if (
                self.input_tokens is None
                or self.output_tokens is None
                or self.error_category is not None
            ):
                raise ValueError("successful samples require usage and no error")
        elif self.error_category is None:
            raise ValueError("unsuccessful samples require an error category")
        return self
