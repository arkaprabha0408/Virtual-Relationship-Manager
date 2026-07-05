from __future__ import annotations

import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.graph.workflow import build_graph  # noqa: E402

NODE_NAMES = ("concierge", "business_intel", "product_expert")


def _content(message) -> str:
    if isinstance(message, dict):
        return message.get("content", "")
    return message.content


def main() -> None:
    client_id_raw = input("client_id: ").strip()
    client_id = int(client_id_raw) if client_id_raw else None

    graph = build_graph()
    thread_id = str(uuid.uuid4())
    config = {"configurable": {"thread_id": thread_id}}

    print("Type your message (Ctrl+C to quit).")
    while True:
        try:
            user_input = input("you> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not user_input:
            continue

        last_agent = "concierge"
        last_reply = ""
        for update in graph.stream(
            {"messages": [{"role": "user", "content": user_input}], "client_id": client_id},
            config=config,
            stream_mode="updates",
        ):
            for node_name, node_output in update.items():
                msgs = node_output.get("messages") or []
                if node_name in NODE_NAMES and msgs:
                    last_agent = node_name
                    last_reply = _content(msgs[-1])

        print(f"[{last_agent}] {last_reply}")


if __name__ == "__main__":
    main()
