"""log_learn — STUB (mealsight.agent.nodes._common.run_stub).

IMPORTANT constraint a later session's real implementation has to
respect: user_intelligence's own log_meal tool is documented (phase
4.3) to be called ONLY after cooking is actually confirmed, never on a
mere recommendation — and this node runs before present, i.e. before
the user has even seen top_recommendation, let alone cooked it. So this
node's real job is NOT "call log_meal here" — that would violate the
exact boundary phase 4.3 established. What it likely does instead:
apply any explicit preference update the request itself stated (via
update_preferences, if merge/reason surfaced one) and/or record that a
recommendation was made for later analytics — with actual meal-cooked
logging deferred to a separate, later, user-confirmed flow outside this
graph entirely.
"""

from __future__ import annotations

from typing import Any

from mealsight.agent.nodes._common import run_stub
from mealsight.agent.state import MealSightState

NODE_NAME = "log_learn"
DESCRIPTION = (
    "Will apply any stated preference updates and record the recommendation for later "
    "analytics — NOT log_meal itself, which only fires after cooking is confirmed, "
    "outside this graph."
)


async def log_learn(state: MealSightState) -> dict[str, Any]:
    return await run_stub(NODE_NAME, DESCRIPTION, state)
