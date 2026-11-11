"""The OpenAI-compatible provider against a fake chat completions server: no key, no network."""

import json

import httpx

from apps.api.agent import tools
from apps.api.agent.providers import OpenAICompatibleProvider


def test_tool_calls_results_and_final_answer_follow_the_chat_completions_format():
    requests = []
    answer = {
        "summary": "Fine.",
        "observations": [{"text": "All fresh.", "evidence": ["call_1"]}],
        "hypotheses": [],
    }
    replies = iter(
        [
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {"name": "get_freshness", "arguments": "{}"},
                    }
                ],
            },
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_2",
                        "type": "function",
                        "function": {"name": "submit_answer", "arguments": json.dumps(answer)},
                    }
                ],
            },
        ]
    )

    def server(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": next(replies)}]})

    client = httpx.Client(base_url="http://fake/v1", transport=httpx.MockTransport(server))
    provider = OpenAICompatibleProvider([tools.schema(n) for n in tools.TOOLS], client=client)

    first = provider.step({"question": "Is our data fresh?", "history": []})
    assert first["calls"] == [{"id": "call_1", "name": "get_freshness", "args": {}}]
    assert requests[0]["messages"][0]["role"] == "system"
    assert {t["function"]["name"] for t in requests[0]["tools"]} >= {
        "list_renewals",
        "submit_answer",
    }

    calls = [{"id": "call_1", "name": "get_freshness", "args": {}, "result": {"rows": []}}]
    second = provider.step(
        {"question": "Is our data fresh?", "transcript": first["transcript"], "calls": calls}
    )
    assert second["answer"] == answer
    sent = requests[1]["messages"]
    assert sent[-2]["tool_calls"][0]["id"] == "call_1"  # the assistant turn is replayed as returned
    assert sent[-1] == {
        "role": "tool",
        "tool_call_id": "call_1",
        "content": json.dumps({"rows": []}),
    }


def test_unreadable_tool_arguments_come_back_as_a_tool_error_not_a_crash():
    reply = {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {
                "id": "call_1",
                "type": "function",
                "function": {"name": "get_freshness", "arguments": '{"source": '},
            }
        ],
    }
    client = httpx.Client(
        base_url="http://fake/v1",
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, json={"choices": [{"message": reply}]})
        ),
    )
    provider = OpenAICompatibleProvider([tools.schema(n) for n in tools.TOOLS], client=client)
    [call] = provider.step({"question": "Is our data fresh?", "history": []})["calls"]
    assert "error" in tools.run(None, call["name"], call["args"])
