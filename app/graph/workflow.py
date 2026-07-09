from __future__ import annotations

from typing import Annotated
from uuid import uuid4

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.tools import BaseTool, InjectedToolCallId, tool
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.prebuilt import InjectedState, create_react_agent
from langgraph.prebuilt.chat_agent_executor import AgentState
from langgraph.types import Command

from app.agents.business_intel import BUSINESS_INTEL_PROMPT
from app.agents.concierge import CONCIERGE_PROMPT
from app.agents.product_expert import PRODUCT_EXPERT_PROMPT
from app.config import settings
from app.tools.cashflow_tools import (
    cash_gaps_tool,
    cashflow_summary_tool,
    category_breakdown_tool,
)
from app.tools.product_tools import (
    eligibility_tool,
    product_details_tool,
    search_products_tool,
)


class VRMState(AgentState):
    client_id: int | None


def get_llm() -> BaseChatModel:
    """Return the chat model configured via LLM_PROVIDER / OPENAI_MODEL. Never hardcode a model name."""
    if settings.llm_provider == "ollama":
        from langchain_ollama import ChatOllama

        return ChatOllama(model="llama3.1:8b", temperature=0)

    from langchain_openai import ChatOpenAI

    return ChatOpenAI(model=settings.openai_model, temperature=0, api_key=settings.openai_api_key)


def _first_handoff_call_id(triggering_message: AIMessage) -> str | None:
    """id of the first handoff-tool call in this AIMessage, or None if it has none.

    A model can call two handoff tools in parallel for a compound query (e.g.
    transfer_to_business_intel and transfer_to_product_expert together). Command-based
    routing can only honor one `goto` target, so only the first such call may actually
    route; any others must still get a real (non-Command) tool result so they don't end
    up as orphaned tool_calls with no matching ToolMessage, which OpenAI rejects on the
    next turn. Disabling parallel tool calls at the API level (`parallel_tool_calls=False`)
    was tried instead and caused gpt-4o-mini to frequently hallucinate a fake
    "{functions.transfer_to_x}" string instead of calling any tool at all — far worse than
    the problem it solved — so this is handled here in code instead.
    """
    handoff_calls = [c for c in (triggering_message.tool_calls or []) if c["name"].startswith("transfer_to_")]
    return handoff_calls[0]["id"] if handoff_calls else None


def _make_handoff_tool(*, agent_name: str, description: str) -> BaseTool:
    tool_name = f"transfer_to_{agent_name}"

    @tool(tool_name, description=description)
    def handoff_tool(
        tool_call_id: Annotated[str, InjectedToolCallId],
        state: Annotated[VRMState, InjectedState],
    ) -> Command | str:
        triggering_message = state["messages"][-1]
        first_id = _first_handoff_call_id(triggering_message)
        if first_id is not None and first_id != tool_call_id:
            return f"Not used: already routing via another handoff tool called in the same turn."

        tool_message = {
            "role": "tool",
            "content": f"Transferred to {agent_name}.",
            "name": tool_name,
            "tool_call_id": tool_call_id,
        }
        return Command(
            goto=agent_name,
            update={
                "messages": state["messages"] + [tool_message],
                "client_id": state.get("client_id"),
            },
            graph=Command.PARENT,
        )

    return handoff_tool


transfer_to_business_intel = _make_handoff_tool(
    agent_name="business_intel",
    description=(
        "Hand off to the Business Intelligence agent for cashflow analysis, "
        "spending categories, and cash-gap questions."
    ),
)
transfer_to_product_expert = _make_handoff_tool(
    agent_name="product_expert",
    description=(
        "Hand off to the Product Expert agent for banking product recommendations "
        "and eligibility checks."
    ),
)


def _make_hand_back_tool(*, from_agent: str, description: str) -> BaseTool:
    """Hand a compound query back to the concierge once this specialist's part is answered.

    Unlike _make_handoff_tool, this carries the specialist's answer as a required tool
    argument rather than relying on the model to also produce it as message content —
    small models reliably call a tool with an argument, but unreliably combine free-text
    content with a tool call in the same completion, which was silently dropping the
    specialist's answer.
    """
    tool_name = "transfer_to_concierge"

    @tool(tool_name, description=description)
    def handoff_tool(
        answer_so_far: Annotated[
            str,
            (
                "Your complete answer to the part of the client's question that IS in "
                "your domain. Passed here as an argument (not as your message text) so it "
                "reaches the client even if you don't also repeat it as message content."
            ),
        ],
        tool_call_id: Annotated[str, InjectedToolCallId],
        state: Annotated[VRMState, InjectedState],
    ) -> Command:
        triggering_message = state["messages"][-1]
        carried_answer = (
            [] if triggering_message.content else [AIMessage(content=answer_so_far, name=from_agent)]
        )
        tool_message = {
            "role": "tool",
            "content": "Transferred to concierge.",
            "name": tool_name,
            "tool_call_id": tool_call_id,
        }
        return Command(
            goto="concierge",
            update={
                # tool_message must come immediately after the triggering AIMessage to
                # pair with its tool_call; any carried-over answer goes after that.
                "messages": state["messages"] + [tool_message] + carried_answer,
                "client_id": state.get("client_id"),
            },
            graph=Command.PARENT,
        )

    return handoff_tool


transfer_to_concierge_from_business_intel = _make_hand_back_tool(
    from_agent="business_intel",
    description=(
        "Hand control back to the concierge because the client's message also asked "
        "about banking products, loans, or eligibility. Pass your complete cashflow "
        "answer as the answer_so_far argument."
    ),
)
transfer_to_concierge_from_product_expert = _make_hand_back_tool(
    from_agent="product_expert",
    description=(
        "Hand control back to the concierge because the client's message also asked "
        "about cashflow, spending, or cash gaps. Pass your complete product answer as "
        "the answer_so_far argument."
    ),
)


def _make_completeness_hook(*, current_agent: str, other_agent: str, model: BaseChatModel):
    """Deterministic safety net for the compound-query hand-back.

    Specialists are prompted to call transfer_to_concierge when the client's message also
    needs the other domain, but small models don't reliably remember to actually call a
    tool after already writing a complete text answer — they sometimes just narrate "I'll
    connect you..." without calling anything, silently dropping the second half of the
    question. This hook runs after every specialist turn that ends without a tool call and
    asks a single cheap yes/no question to catch that case, forcing the handoff in code
    instead of hoping the model remembers.
    """

    async def hook(state: VRMState) -> dict:
        messages = state["messages"]
        last_ai = next(m for m in reversed(messages) if isinstance(m, AIMessage))
        if last_ai.tool_calls:
            return {}

        last_human_idx = max(i for i, m in enumerate(messages) if isinstance(m, HumanMessage))
        turn_messages = messages[last_human_idx + 1 :]
        other_already_answered = any(
            isinstance(m, AIMessage) and getattr(m, "name", None) == other_agent and m.content
            for m in turn_messages
        )
        if other_already_answered or not last_ai.content:
            return {}

        original_query = messages[last_human_idx].content
        verdict = await model.ainvoke(
            [
                SystemMessage(
                    content=(
                        f"The client asked: {original_query!r}\n\n"
                        f"The {current_agent} specialist just answered the part of this in "
                        f"their own domain. Your ONLY job is to check for a SECOND, "
                        f"CLEARLY DISTINCT question in that same message that belongs to "
                        f"the {other_agent} specialist's domain instead.\n\n"
                        "Default to 'no'. Only answer 'yes' if the client's message "
                        "explicitly asks about both topics — never infer or guess an "
                        "unstated second need, and never answer 'yes' just because the "
                        f"topics are related or the {current_agent} specialist mentioned "
                        f"{other_agent} in passing. Reply with exactly one word: yes or no."
                    )
                )
            ]
        )
        if "yes" not in (verdict.content or "").strip().lower():
            return {}

        handoff_message = AIMessage(
            content="",
            name=current_agent,
            tool_calls=[
                {
                    "name": "transfer_to_concierge",
                    "args": {"answer_so_far": last_ai.content},
                    "id": f"handback-{uuid4().hex}",
                    "type": "tool_call",
                }
            ],
        )
        return {"messages": [handoff_message]}

    return hook


def _with_client_context(base_prompt: str):
    def _prompt(state: VRMState) -> list:
        client_id = state.get("client_id")
        system = base_prompt
        if client_id is not None:
            system = (
                f"{base_prompt}\n\nCurrent client_id: {client_id}. Use this client_id "
                "when calling tools unless the user clearly names another client."
            )
        return [SystemMessage(content=system), *state["messages"]]

    return _prompt


def build_graph(
    llm: BaseChatModel | None = None,
    checkpointer: BaseCheckpointSaver | None = None,
) -> CompiledStateGraph:
    """Assemble the concierge/business_intel/product_expert StateGraph. Single code path for tests and FastAPI."""
    model = llm or get_llm()

    concierge_tools = [transfer_to_business_intel, transfer_to_product_expert]
    business_intel_tools = [
        cashflow_summary_tool,
        category_breakdown_tool,
        cash_gaps_tool,
        transfer_to_concierge_from_business_intel,
    ]
    product_expert_tools = [
        search_products_tool,
        product_details_tool,
        eligibility_tool,
        transfer_to_concierge_from_product_expert,
    ]

    concierge_agent = create_react_agent(
        model,
        concierge_tools,
        prompt=_with_client_context(CONCIERGE_PROMPT),
        state_schema=VRMState,
        name="concierge",
    )
    business_intel_agent = create_react_agent(
        model,
        business_intel_tools,
        prompt=_with_client_context(BUSINESS_INTEL_PROMPT),
        state_schema=VRMState,
        name="business_intel",
        post_model_hook=_make_completeness_hook(
            current_agent="business_intel", other_agent="product_expert", model=model
        ),
    )
    product_expert_agent = create_react_agent(
        model,
        product_expert_tools,
        prompt=_with_client_context(PRODUCT_EXPERT_PROMPT),
        state_schema=VRMState,
        name="product_expert",
        post_model_hook=_make_completeness_hook(
            current_agent="product_expert", other_agent="business_intel", model=model
        ),
    )

    builder = StateGraph(VRMState)
    builder.add_node("concierge", concierge_agent)
    builder.add_node("business_intel", business_intel_agent)
    builder.add_node("product_expert", product_expert_agent)

    builder.add_edge(START, "concierge")
    builder.add_edge("concierge", END)
    builder.add_edge("business_intel", END)
    builder.add_edge("product_expert", END)

    return builder.compile(checkpointer=checkpointer or MemorySaver())
