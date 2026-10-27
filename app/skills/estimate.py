"""The estimate of a skill by box tier: which model roles are used, and their prices.

Prices come from the model catalog only. A role without a catalog entry is shown as "not found",
never filled from memory."""

from app.agent.catalog import ModelCatalog
from app.i18n import Translator
from skillkit.parse import SkillDoc

# the capability name used by the model catalog for each role of the box
CAPABILITY = {
    "reasoning": "text",
    "fast": "text",
    "code": "text",
    "vision": "vision",
    "image": "image",
    "video": "video",
    "tts": "tts",
    "asr": "asr",
}


def estimate_view(doc: SkillDoc, catalog: ModelCatalog) -> list[dict]:
    tiers = []
    for tier in doc.tiers:
        roles = []
        for role in tier.roles:
            capability = CAPABILITY.get(role)
            entries = catalog.lookup(capability) if capability else []
            roles.append(
                {
                    "role": role,
                    "capability": capability,
                    "models": [
                        {"model_id": e.model_id, "prices": e.prices, "synced_at": e.synced_at}
                        for e in entries[:1]
                    ],
                }
            )
        tiers.append({"id": tier.id, "includes": tier.includes, "roles": roles})
    return tiers


def estimate_text(tr: Translator, tenant: str, doc: SkillDoc, catalog: ModelCatalog) -> str:
    """The estimate as lines for the chat."""
    lines = [tr.t(tenant, "run_estimate_head")]
    for tier in estimate_view(doc, catalog):
        roles = ", ".join(r["role"] for r in tier["roles"])
        lines.append(
            tr.t(tenant, "run_estimate_tier", tier=tr.t(tenant, f"tier_{tier['id']}"), roles=roles)
        )
        for role in tier["roles"]:
            if role["capability"] is None:
                continue
            if role["models"]:
                m = role["models"][0]
                lines.append(
                    tr.t(
                        tenant,
                        "price_line",
                        model_id=m["model_id"],
                        capability=role["capability"],
                        prices=m["prices"],
                        synced_at=m["synced_at"],
                    )
                )
            else:
                lines.append(tr.t(tenant, "price_not_found", query=role["role"]))
    return "\n".join(lines)
