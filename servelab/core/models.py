from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Message(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    role: Literal["system", "user", "assistant"]
    content: str = Field(min_length=1, max_length=16384)


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)

    model: str = Field(min_length=1, max_length=200)
    messages: list[Message] = Field(min_length=1, max_length=128)
    stream: bool = False
    max_tokens: int = Field(default=32, ge=1, le=1024)
    temperature: float = Field(default=0.0, ge=0, le=2)


class GatewayError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message

    def payload(self, request_id: str) -> dict:
        return {
            "error": {"message": self.message, "type": self.code, "code": self.code},
            "request_id": request_id,
        }
