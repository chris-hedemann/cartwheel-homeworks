"""Read-only probe: list item types of one run. Order lookup only, no DB writes. Do not commit."""
import asyncio
from agents import Runner, RunConfig
from agent.agent import build_agent
from agent.auth import AuthContext

async def main():
    ctx = AuthContext(user_id=1, role="shopper", store_id=None)
    agent = build_agent(ctx)
    r = await Runner.run(agent, "Show me order 4127", context=ctx, max_turns=10,
                         run_config=RunConfig(tracing_disabled=True))
    for i, it in enumerate(r.new_items):
        extra = ""
        if it.type == "message_output_item":
            extra = repr(getattr(it.raw_item, "content", None))[:300]
        elif it.type == "tool_call_item":
            extra = getattr(it.raw_item, "name", "")
        print(i, it.type, extra)
    print("FINAL:", str(r.final_output)[:200])

asyncio.run(main())
