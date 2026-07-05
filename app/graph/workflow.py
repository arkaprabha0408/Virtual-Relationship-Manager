from __future__ import annotations

from typing import Annotated

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import SystemMessage
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


def _make_handoff_tool(*, agent_name: str, description: str) -> BaseTool:
    tool_name = f"transfer_to_{agent_name}"

    @tool(tool_name, description=description)
    def handoff_tool(
        tool_call_id: Annotated[str, InjectedToolCallId],
        state: Annotated[VRMState, InjectedState],
    ) -> Command:
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

    concierge_agent = create_react_agent(
        model,
        [transfer_to_business_intel, transfer_to_product_expert],
        prompt=_with_client_context(CONCIERGE_PROMPT),
        state_schema=VRMState,
        name="concierge",
    )
    business_intel_agent = create_react_agent(
        model,
        [cashflow_summary_tool, category_breakdown_tool, cash_gaps_tool],
        prompt=_with_client_context(BUSINESS_INTEL_PROMPT),
        state_schema=VRMState,
        name="business_intel",
    )
    product_expert_agent = create_react_agent(
        model,
        [search_products_tool, product_details_tool, eligibility_tool],
        prompt=_with_client_context(PRODUCT_EXPERT_PROMPT),
        state_schema=VRMState,
        name="product_expert",
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
