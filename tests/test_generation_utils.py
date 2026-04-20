"""Tests for utils/generation_utils.py."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import utils.generation_utils as gen_utils
from utils.generation_utils import call_model_with_retry_async, reinitialize_clients
from utils.bedrock_client import BedrockInvocationError


def _make_bedrock_response(text: str = "Mock response") -> dict:
    return {
        "content": [{"type": "text", "text": text}],
        "stop_reason": "end_turn",
        "usage": {"input_tokens": 10, "output_tokens": 5},
    }


@pytest.fixture(autouse=True)
def reset_module_client():
    """Reset the module-level _bedrock_client before each test."""
    gen_utils._bedrock_client = None
    yield
    gen_utils._bedrock_client = None


class TestRouting:
    async def test_routes_anthropic_prefix_to_bedrock(self, mock_boto3_client):
        _, _, mock_client = mock_boto3_client
        mock_client.invoke_model.return_value = _make_raw_response("Routed to Bedrock")

        result = await call_model_with_retry_async(
            model_name="anthropic.claude-3-sonnet-20240229-v1:0",
            contents=[{"type": "text", "text": "Hello"}],
        )
        assert isinstance(result, list)
        assert len(result) == 1

    async def test_routes_global_anthropic_prefix(self, mock_boto3_client):
        _, _, mock_client = mock_boto3_client
        mock_client.invoke_model.return_value = _make_raw_response("global route")

        result = await call_model_with_retry_async(
            model_name="global.anthropic.claude-sonnet-4-6",
            contents=[{"type": "text", "text": "Hello"}],
        )
        assert isinstance(result, list)

    async def test_routes_apac_anthropic_prefix(self, mock_boto3_client):
        _, _, mock_client = mock_boto3_client
        mock_client.invoke_model.return_value = _make_raw_response("apac route")

        result = await call_model_with_retry_async(
            model_name="apac.anthropic.claude-sonnet-4-6",
            contents=[{"type": "text", "text": "Hello"}],
        )
        assert isinstance(result, list)

    async def test_routes_us_anthropic_prefix(self, mock_boto3_client):
        _, _, mock_client = mock_boto3_client
        mock_client.invoke_model.return_value = _make_raw_response("us route")

        result = await call_model_with_retry_async(
            model_name="us.anthropic.claude-3-sonnet-20240229-v1:0",
            contents=[{"type": "text", "text": "Hello"}],
        )
        assert isinstance(result, list)

    async def test_rejects_unsupported_model_with_value_error(self):
        with pytest.raises(ValueError, match="Unsupported model"):
            await call_model_with_retry_async(
                model_name="gemini-1.5-pro",
                contents=[{"type": "text", "text": "Hello"}],
            )

    async def test_rejects_openai_model_with_value_error(self):
        with pytest.raises(ValueError):
            await call_model_with_retry_async(
                model_name="gpt-4o",
                contents=[{"type": "text", "text": "Hello"}],
            )


class TestContentsConversion:
    async def test_text_contents_converted_to_bedrock_messages(self, mock_boto3_client):
        _, _, mock_client = mock_boto3_client
        mock_client.invoke_model.return_value = _make_raw_response("ok")

        await call_model_with_retry_async(
            model_name="global.anthropic.claude-sonnet-4-6",
            contents=[{"type": "text", "text": "What is 2+2?"}],
        )

        call_kwargs = mock_client.invoke_model.call_args
        body = json.loads(call_kwargs.kwargs["body"])
        assert body["messages"][0]["role"] == "user"
        assert body["messages"][0]["content"][0]["text"] == "What is 2+2?"

    async def test_multiple_text_items_merged_in_single_user_message(self, mock_boto3_client):
        _, _, mock_client = mock_boto3_client
        mock_client.invoke_model.return_value = _make_raw_response("ok")

        await call_model_with_retry_async(
            model_name="global.anthropic.claude-sonnet-4-6",
            contents=[
                {"type": "text", "text": "First"},
                {"type": "text", "text": "Second"},
            ],
        )

        call_kwargs = mock_client.invoke_model.call_args
        body = json.loads(call_kwargs.kwargs["body"])
        content_blocks = body["messages"][0]["content"]
        assert len(content_blocks) == 2
        assert content_blocks[0]["text"] == "First"
        assert content_blocks[1]["text"] == "Second"


class TestConfigForwarding:
    async def test_system_prompt_forwarded(self, mock_boto3_client):
        _, _, mock_client = mock_boto3_client
        mock_client.invoke_model.return_value = _make_raw_response("ok")

        await call_model_with_retry_async(
            model_name="global.anthropic.claude-sonnet-4-6",
            contents=[{"type": "text", "text": "Hello"}],
            config={"system_prompt": "You are a pirate.", "max_tokens": 100, "temperature": 0.5},
        )

        call_kwargs = mock_client.invoke_model.call_args
        body = json.loads(call_kwargs.kwargs["body"])
        assert body["system"] == "You are a pirate."
        assert body["max_tokens"] == 100
        assert body["temperature"] == 0.5

    async def test_config_none_uses_defaults(self, mock_boto3_client):
        _, _, mock_client = mock_boto3_client
        mock_client.invoke_model.return_value = _make_raw_response("ok")

        await call_model_with_retry_async(
            model_name="global.anthropic.claude-sonnet-4-6",
            contents=[{"type": "text", "text": "Hello"}],
            config=None,
        )

        call_kwargs = mock_client.invoke_model.call_args
        body = json.loads(call_kwargs.kwargs["body"])
        assert body["max_tokens"] == 4096
        assert body["temperature"] == 0.7


class TestReturnType:
    async def test_returns_list_of_strings(self, mock_boto3_client):
        _, _, mock_client = mock_boto3_client
        mock_client.invoke_model.return_value = _make_raw_response("The answer is 42.")

        result = await call_model_with_retry_async(
            model_name="global.anthropic.claude-sonnet-4-6",
            contents=[{"type": "text", "text": "Hello"}],
        )

        assert isinstance(result, list)
        assert all(isinstance(s, str) for s in result)
        assert result[0] == "The answer is 42."

    async def test_returns_one_element_for_single_shot(self, mock_boto3_client):
        _, _, mock_client = mock_boto3_client
        mock_client.invoke_model.return_value = _make_raw_response("Single shot.")

        result = await call_model_with_retry_async(
            model_name="global.anthropic.claude-sonnet-4-6",
            contents=[{"type": "text", "text": "Hi"}],
        )

        assert len(result) == 1


class TestReinitializeClients:
    def test_reinitialize_returns_list(self):
        result = reinitialize_clients()
        assert isinstance(result, list)
        assert "Bedrock" in result

    def test_reinitialize_resets_client(self, mock_boto3_client):
        # Force client creation
        gen_utils._bedrock_client = MagicMock()
        reinitialize_clients()
        assert gen_utils._bedrock_client is None


# --- Helper ---

def _make_raw_response(text: str) -> dict:
    import json
    body_bytes = json.dumps(
        {
            "content": [{"type": "text", "text": text}],
            "stop_reason": "end_turn",
            "usage": {"input_tokens": 5, "output_tokens": 3},
        }
    ).encode()
    mock_body = MagicMock()
    mock_body.read.return_value = body_bytes
    return {"body": mock_body}
