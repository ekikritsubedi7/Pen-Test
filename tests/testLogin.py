import json
import unittest
from unittest.mock import patch

from pentestgpt.config.chat_config import ChatGPTConfig
from pentestgpt.utils.chatgpt import ChatGPT


class MockStreamResponse:
    def __init__(self, payload):
        self.status_code = 200
        self._payload = payload

    def iter_lines(self):
        yield f"data: {json.dumps(self._payload)}".encode("utf-8")
        yield b"data: [DONE]"


class TestLogin(unittest.TestCase):
    def setUp(self):
        self.auth_patcher = patch.object(
            ChatGPT, "get_authorization", return_value="Bearer test-token"
        )
        self.auth_patcher.start()
        self.addCleanup(self.auth_patcher.stop)

        self.chatgpt_config = ChatGPTConfig()
        self.chatgpt_config.cookie = "session=test"
        self.chatgpt = ChatGPT(self.chatgpt_config)

    def test_send_new_message_returns_text_and_conversation_id(self):
        payload = {
            "message": {"content": {"parts": ["hello"]}, "id": "message-id"},
            "conversation_id": "conversation-id",
        }
        mock_response = MockStreamResponse(payload)

        with patch("pentestgpt.utils.chatgpt.requests.post", return_value=mock_response):
            with patch.object(
                self.chatgpt,
                "_parse_message_raw_output",
                return_value=payload,
            ):
                text, conversation_id = self.chatgpt.send_new_message("Hi there")

        self.assertEqual(text, "hello")
        self.assertEqual(conversation_id, "conversation-id")

    def test_parse_message_raw_output_returns_last_data_block(self):
        payload = {
            "message": {"content": {"parts": ["payload"]}},
            "conversation_id": "conversation",
        }

        stream = MockStreamResponse(payload)
        parsed = self.chatgpt._parse_message_raw_output(stream)
        self.assertEqual(parsed, payload)


if __name__ == "__main__":
    unittest.main()
