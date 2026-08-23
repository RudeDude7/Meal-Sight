"""Provider-agnostic interfaces and response types.

Application code should depend on these abstract classes (TextProvider,
VisionProvider, AudioProvider), not on the concrete Mistral/Groq
implementations, so swapping a provider later is a matter of implementing
the interface again, not rewriting every call site.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TypeVar

from pydantic import BaseModel

SchemaT = TypeVar("SchemaT", bound=BaseModel)


@dataclass(frozen=True, slots=True)
class TextResponse:
    text: str
    model_id: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    latency_ms: float


@dataclass(frozen=True, slots=True)
class TranscriptionResponse:
    text: str
    model_id: str
    latency_ms: float


class TextProvider(ABC):
    """A provider capable of text completion, including structured
    (schema-validated) JSON completion."""

    @abstractmethod
    async def complete(
        self,
        prompt: str,
        model_id: str,
        *,
        system: str | None = None,
        max_tokens: int | None = None,
        temperature: float = 0.0,
    ) -> TextResponse: ...

    @abstractmethod
    async def complete_json(
        self,
        prompt: str,
        schema: type[SchemaT],
        model_id: str,
        *,
        system: str | None = None,
        max_tokens: int | None = None,
        temperature: float = 0.0,
    ) -> SchemaT:
        """Requests JSON output, parses it, and validates it against
        `schema`. Raises InvalidResponse if the model's output never
        validates, even after one repair attempt."""
        ...


class VisionProvider(ABC):
    """A provider capable of describing the contents of an image."""

    @abstractmethod
    async def analyze_image(
        self,
        image_bytes: bytes,
        prompt: str,
        model_id: str,
        *,
        system: str | None = None,
    ) -> TextResponse: ...


class AudioProvider(ABC):
    """A provider capable of transcribing spoken audio to text."""

    @abstractmethod
    async def transcribe(self, audio_bytes: bytes, filename: str, model_id: str) -> TranscriptionResponse: ...
