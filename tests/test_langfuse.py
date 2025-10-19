import os
import unittest
from unittest.mock import MagicMock, patch

from pentestgpt.config.chat_config import ChatGPTConfig
from pentestgpt.utils.APIs.chatgpt_api import ChatGPTAPI


class TestLangfuseIntegration(unittest.TestCase):
    @patch("pentestgpt.utils.APIs.chatgpt_api.OpenAI")
    def test_langfuse_logging_sets_environment_and_client(self, mock_openai):
        config = ChatGPTConfig()
        config.model = "gpt-4o"
        config.log_dir = "logs"

        with patch("pentestgpt.utils.APIs.chatgpt_api.Langfuse") as mock_langfuse:
            mock_instance = MagicMock()
            mock_langfuse.return_value = mock_instance

            api = ChatGPTAPI(config, use_langfuse_logging=True)

        self.assertTrue(hasattr(api, "langfuse"))
        self.assertEqual(api.langfuse, mock_instance)
        self.assertEqual(
            os.environ.get("LANGFUSE_PUBLIC_KEY"),
            "pk-lf-5655b061-3724-43ee-87bb-28fab0b5f676",
        )
        self.assertEqual(
            os.environ.get("LANGFUSE_SECRET_KEY"),
            "sk-lf-c24b40ef-8157-44af-a840-6bae2c9358b0",
        )
        mock_openai.assert_called_once_with(
            api_key=config.openai_key, base_url=config.api_base
        )


if __name__ == "__main__":
    unittest.main()
