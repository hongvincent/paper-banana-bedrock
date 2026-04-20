"""Tests for utils/bedrock_client.py."""

import json
import os
from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError

from utils.bedrock_client import BedrockClient, BedrockInvocationError


def _client_error(code: str) -> ClientError:
    return ClientError(
        error_response={"Error": {"Code": code, "Message": code}},
        operation_name="InvokeModel",
    )


def _make_invoke_response(text: str = "Hi there") -> dict:
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


class TestBedrockClientInstantiation:
    def test_defaults_from_env(self, mock_boto3_client):
        with patch.dict(
            os.environ,
            {
                "AWS_REGION": "us-east-1",
                "BEDROCK_MODEL_ID": "global.anthropic.claude-sonnet-4-6",
                "BEDROCK_MAX_TOKENS": "2048",
                "BEDROCK_TEMPERATURE": "0.5",
            },
            clear=False,
        ):
            client = BedrockClient()
        assert client.region == "us-east-1"
        assert client.model_id == "global.anthropic.claude-sonnet-4-6"
        assert client._max_tokens_default == 2048
        assert client._temperature_default == 0.5

    def test_explicit_params_override_env(self, mock_boto3_client):
        client = BedrockClient(
            region="eu-west-1",
            profile=None,
            model_id="global.anthropic.claude-sonnet-4-6",
        )
        assert client.region == "eu-west-1"
        assert client.model_id == "global.anthropic.claude-sonnet-4-6"

    def test_boto3_session_created_with_profile(self):
        mock_client = MagicMock()
        mock_client.invoke_model.return_value = _make_invoke_response()
        mock_session = MagicMock()
        mock_session.client.return_value = mock_client

        with patch("boto3.Session", return_value=mock_session) as mock_sess_cls:
            BedrockClient(region="ap-northeast-2", profile="test-profile")
            mock_sess_cls.assert_called_once_with(profile_name="test-profile")
            mock_session.client.assert_called_once_with(
                "bedrock-runtime", region_name="ap-northeast-2"
            )


class TestBedrockClientInvokeText:
    async def test_success_returns_content(self, mock_boto3_client):
        _, _, mock_client = mock_boto3_client
        mock_client.invoke_model.return_value = _make_invoke_response("Howdy!")

        client = BedrockClient()
        result = await client.invoke_text(
            messages=[{"role": "user", "content": [{"type": "text", "text": "hi"}]}],
            max_tokens=100,
            temperature=0.5,
        )

        assert result["content"][0]["text"] == "Howdy!"
        assert result["stop_reason"] == "end_turn"
        assert "usage" in result

    async def test_passes_system_prompt(self, mock_boto3_client):
        _, _, mock_client = mock_boto3_client
        mock_client.invoke_model.return_value = _make_invoke_response()

        client = BedrockClient()
        await client.invoke_text(
            messages=[{"role": "user", "content": [{"type": "text", "text": "hello"}]}],
            max_tokens=100,
            temperature=0.7,
            system="You are a helpful assistant.",
        )

        call_kwargs = mock_client.invoke_model.call_args
        body = json.loads(call_kwargs.kwargs["body"])
        assert body["system"] == "You are a helpful assistant."

    async def test_retry_on_throttling(self, mock_boto3_client):
        """Client should retry ThrottlingException and succeed on third attempt."""
        _, _, mock_client = mock_boto3_client
        mock_client.invoke_model.side_effect = [
            _client_error("ThrottlingException"),
            _client_error("ThrottlingException"),
            _make_invoke_response("finally"),
        ]

        client = BedrockClient()
        # Speed up test by patching sleep
        with patch("asyncio.sleep"):
            result = await client.invoke_text(
                messages=[{"role": "user", "content": [{"type": "text", "text": "ping"}]}],
                max_tokens=50,
                temperature=0.7,
            )

        assert result["content"][0]["text"] == "finally"
        assert mock_client.invoke_model.call_count == 3

    async def test_raises_bedrock_invocation_error_after_max_retries(self, mock_boto3_client):
        """After all retries exhausted, BedrockInvocationError should be raised."""
        _, _, mock_client = mock_boto3_client
        mock_client.invoke_model.side_effect = _client_error("ThrottlingException")

        client = BedrockClient()
        with patch("asyncio.sleep"):
            with pytest.raises(BedrockInvocationError) as exc_info:
                await client.invoke_text(
                    messages=[{"role": "user", "content": [{"type": "text", "text": "ping"}]}],
                    max_tokens=50,
                    temperature=0.7,
                )

        assert "ThrottlingException" in str(exc_info.value) or exc_info.value.__cause__ is not None

    async def test_non_retryable_error_raises_immediately(self, mock_boto3_client):
        """Non-retryable ClientError should raise BedrockInvocationError without retrying."""
        _, _, mock_client = mock_boto3_client
        mock_client.invoke_model.side_effect = _client_error("ValidationException")

        client = BedrockClient()
        with pytest.raises(BedrockInvocationError):
            await client.invoke_text(
                messages=[{"role": "user", "content": [{"type": "text", "text": "bad"}]}],
                max_tokens=50,
                temperature=0.7,
            )

        assert mock_client.invoke_model.call_count == 1
