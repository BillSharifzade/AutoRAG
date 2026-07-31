"""Launch the KARAG HTTP app (console /ui, builder /builder, REST /v1/*).

Reads provider + auth config from the environment (load .env first). Registers
the sample sales skills so the data plane is exercisable in the browser; shares
the configured store with the Telegram bot, so seeded documents are visible.
"""

from __future__ import annotations

import os

import uvicorn

from karag.api.app import create_app
from karag.api.security import InMemoryResolver
from karag.config import Settings
from karag.factory import build_platform
from karag.skills.registry import SkillRegistry
from karag.skills.authoring import authoring_skills
from karag.skills.samples import sales_by_store_skill, sales_report_skill
from karag.tenants import ChainResolver, DirectoryResolver

registry = SkillRegistry()

# File-authoring skills are product features — always available.
for _skill in authoring_skills():
    registry.register(_skill)

# The sample sales skills return hard-coded fake data. Now that skills are
# authored at runtime and stored, leaving them on shadows real ones: two tools
# both claim to answer "sales for a store" and the model may pick the fake.
# Opt in with KARAG_DEMO_SKILLS=1 when you want the offline demo data.
if os.environ.get("KARAG_DEMO_SKILLS") == "1":
    registry.register(sales_by_store_skill(tenant_id="koinoti"))
    registry.register(sales_report_skill(tenant_id="koinoti"))

platform = build_platform(Settings.from_env(), registry=registry)

# Env tokens (dev, bots) and database accounts (onboarded users) both work:
# the chain tries the static map first, then the accounts table.
app = create_app(
    platform,
    ChainResolver(InMemoryResolver.from_env(), DirectoryResolver(platform.directory)),
)

if __name__ == "__main__":
    host = os.environ.get("KARAG_HOST", "127.0.0.1")
    port = int(os.environ.get("KARAG_PORT", "8000"))
    for err in platform.skill_load_errors:
        print(f"[karag-web] stored skill failed to load: {err}", flush=True)
    print(f"[karag-web] http://{host}:{port}/ui  ·  builder /builder  ·  "
          f"demo token: tkn_ceo", flush=True)
    uvicorn.run(app, host=host, port=port, log_level="info")
