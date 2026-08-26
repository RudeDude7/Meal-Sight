"""The typed, versioned WebSocket message envelope — one pydantic model
per message type, so the frontend contract is explicit rather than "a
dict shaped like whatever the backend happened to send." Every message
carries session_id and timestamp regardless of type; version is a
schema version (bump it, don't silently change an existing type's own
fields), not a protocol negotiation — there's exactly one version today.

MESSAGE_CLASSES_BY_TYPE maps each type's own string discriminator to its
model, letting mealsight.api.streaming.SessionStream build the right one
from a bare (event_type, **fields) call without every node needing to
import pydantic models that are properly this module's own concern, not
mealsight.agent's.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field

WS_PROTOCOL_VERSION = 1


class BaseWSMessage(BaseModel):
    # Declared here (not just on each subclass) purely so code holding a
    # plain BaseWSMessage — mealsight.api.streaming's own buffer/queues,
    # typed broadly since they hold every message type interchangeably —
    # can still check .type without narrowing to a specific subclass
    # first. Every real instance is always one of the Literal-typed
    # subclasses below; this is never constructed directly.
    type: str
    version: int = WS_PROTOCOL_VERSION
    session_id: str
    timestamp: datetime


class NodeStartMessage(BaseWSMessage):
    type: Literal["node_start"] = "node_start"
    node: str


class NodeCompleteMessage(BaseWSMessage):
    type: Literal["node_complete"] = "node_complete"
    node: str
    duration_ms: float


class IngredientFoundMessage(BaseWSMessage):
    """perceive's own per-modality progress event — see that node's own
    docstring for why "ingredient_found" is the type used for all three
    modalities (vision/audio/text), not just vision specifically."""

    type: Literal["ingredient_found"] = "ingredient_found"
    modality: Literal["vision", "audio", "text"]
    message: str


class RecipeMatchMessage(BaseWSMessage):
    type: Literal["recipe_match"] = "recipe_match"
    recipe_id: str
    name: str | None = None
    match_score: float | None = None
    can_cook: bool | None = None


class RecommendationMessage(BaseWSMessage):
    type: Literal["recommendation"] = "recommendation"
    recipe_id: str | None
    summary: str
    available: bool


class StreamTokenMessage(BaseWSMessage):
    """Defined for schema completeness (message envelopes must validate
    against their schemas regardless of whether every type is ever
    actually emitted) — reason (node 8) does NOT emit this type today.
    mealsight.providers has no streaming support at all (checked before
    writing this phase's own work — see reason.py's own module
    docstring), so there is no real token boundary to stream; sending
    the reasoning model's complete output as fake, artificially-chunked
    "tokens" would be exactly the kind of faking this was built not to
    do. This model exists so a future provider that DOES support
    streaming has a real, already-reviewed schema to emit against."""

    type: Literal["stream_token"] = "stream_token"
    token: str
    index: int | None = None


class ErrorMessage(BaseWSMessage):
    type: Literal["error"] = "error"
    code: str
    message: str


class CompleteMessage(BaseWSMessage):
    type: Literal["complete"] = "complete"
    result: dict[str, Any]


_WSMessageUnion = (
    NodeStartMessage
    | NodeCompleteMessage
    | IngredientFoundMessage
    | RecipeMatchMessage
    | RecommendationMessage
    | StreamTokenMessage
    | ErrorMessage
    | CompleteMessage
)
WSMessage = Annotated[_WSMessageUnion, Field(discriminator="type")]

MESSAGE_CLASSES_BY_TYPE: dict[str, type[BaseWSMessage]] = {
    "node_start": NodeStartMessage,
    "node_complete": NodeCompleteMessage,
    "ingredient_found": IngredientFoundMessage,
    "recipe_match": RecipeMatchMessage,
    "recommendation": RecommendationMessage,
    "stream_token": StreamTokenMessage,
    "error": ErrorMessage,
    "complete": CompleteMessage,
}
