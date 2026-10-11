from typing import Literal

from pydantic import BaseModel, Field, model_validator


class SakinaChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=4000)


class SakinaChatRequest(BaseModel):
    history: list[SakinaChatMessage] = Field(min_length=1, max_length=40)

    @model_validator(mode="after")
    def validate_transcript(self):
        if self.history[-1].role != "user":
            raise ValueError("The final chat message must be from the user")
        if sum(len(message.content) for message in self.history) > 20000:
            raise ValueError("The conversation is too long; start a new chat")
        return self


class SakinaEmergencyNumber(BaseModel):
    label: str
    number: str


class SakinaChatResponse(BaseModel):
    reply: str = Field(min_length=1, max_length=5000)
    crisis: bool = False
    fallback: bool = False
    emergency_numbers: list[SakinaEmergencyNumber] = Field(default_factory=list)
