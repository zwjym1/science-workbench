from datetime import datetime, timezone
from typing import Literal
from pydantic import BaseModel, Field, HttpUrl, AwareDatetime, ConfigDict, field_validator
from typing import Annotated

class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid')

class CommentInput(StrictModel):
    external_id: str = Field(min_length=1, max_length=200)
    text: str = Field(min_length=1, max_length=10000)
    likes: int | None = Field(default=None, ge=0)

class VideoInput(StrictModel):
    platform: str = Field(min_length=1, max_length=40)
    external_id: str = Field(min_length=1, max_length=200)
    title: str = Field(min_length=1, max_length=2000)
    source_url: HttpUrl
    collected_at: AwareDatetime
    published_at: AwareDatetime | None = None
    content: str | None = Field(default=None, max_length=100000)
    comments: list[CommentInput] = Field(default_factory=list, max_length=5000)
    related_searches: list[str] = Field(default_factory=list, max_length=500)
    tags: list[str] = Field(default_factory=list, max_length=100)
    metrics: dict[str, Annotated[int, Field(ge=0)] | None] = Field(default_factory=dict)

    @field_validator('collected_at', 'published_at')
    @classmethod
    def utc_time(cls, value):
        return value.astimezone(timezone.utc) if value is not None else None

class StandardData(StrictModel):
    videos: list[VideoInput] = Field(min_length=1, max_length=200)

class ImportRequest(StrictModel):
    adapter: Literal['standard-json'] = 'standard-json'
    is_demo: bool
    data: StandardData

class LoginRequest(BaseModel):
    password: str = Field(max_length=500)
