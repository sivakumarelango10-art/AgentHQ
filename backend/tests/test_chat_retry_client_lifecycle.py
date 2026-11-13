import unittest
from unittest.mock import patch

from app import main


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class FakeAsyncClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.closed = False
        self.calls = []

    async def __aenter__(self):
        self.closed = False
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        self.closed = True

    async def post(self, url, json):
        if self.closed:
            raise RuntimeError("Cannot send a request, as the client has been closed.")
        self.calls.append((url, json))
        return FakeResponse(self.responses.pop(0))


class ChatRetryClientLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def test_sanitization_retry_uses_client_before_it_closes(self):
        fake_client = FakeAsyncClient(
            [
                {
                    "message": {
                        "content": "Okay, the user wants me to confirm the runtime. Mental note: be concise."
                    },
                    "done_reason": "stop",
                },
                {
                    "message": {
                        "content": "AgentHQ runtime connection confirmed. I am Atlas, ready to coordinate the team."
                    },
                    "done_reason": "stop",
                },
            ]
        )
        agent = {
            "id": "atlas",
            "name": "Atlas",
            "role": "AI Orchestrator",
            "department": "Management",
            "room": "CEO Office",
        }
        stored_messages = []

        def add_message(conversation_id, role, content):
            item = {
                "id": f"message-{len(stored_messages) + 1}",
                "conversation_id": conversation_id,
                "role": role,
                "content": content,
                "created_at": "2026-11-13T00:00:00+00:00",
            }
            stored_messages.append(item)
            return item

        with (
            patch.object(main.db, "get_agent", return_value=agent),
            patch.object(
                main.db,
                "get_conversation",
                return_value={"id": "conversation-1", "agent_id": "atlas"},
            ),
            patch.object(main.db, "add_conversation_message", side_effect=add_message),
            patch.object(
                main.db,
                "list_conversation_messages",
                return_value=[
                    {
                        "role": "user",
                        "content": "Reply with the exact connection confirmation.",
                    }
                ],
            ),
            patch.object(main.db, "set_agent_activity"),
            patch.object(main.httpx, "AsyncClient", return_value=fake_client),
        ):
            result = await main.chat_with_agent(
                "atlas",
                main.ChatRequest(
                    message="Reply with the exact connection confirmation.",
                    conversation_id="conversation-1",
                ),
            )

        self.assertEqual(len(fake_client.calls), 2)
        self.assertTrue(fake_client.closed)
        self.assertEqual(
            result["assistant_message"]["content"],
            "AgentHQ runtime connection confirmed. I am Atlas, ready to coordinate the team.",
        )
        self.assertEqual(stored_messages[-1]["role"], "assistant")
        self.assertNotIn("Mental note", stored_messages[-1]["content"])
        self.assertEqual(
            fake_client.calls[1][1]["options"]["temperature"],
            0.3,
        )


if __name__ == "__main__":
    unittest.main()
