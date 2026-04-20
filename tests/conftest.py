"""Shared pytest fixtures for paper-banana-bedrock tests."""

import json
from unittest.mock import MagicMock, patch

import pytest


def _make_canned_response(text: str = "Hello from Bedrock") -> dict:
    """Build a minimal Bedrock response dict matching the Anthropic messages format."""
    body_bytes = json.dumps(
        {
            "id": "msg_test",
            "type": "message",
            "role": "assistant",
            "content": [{"type": "text", "text": text}],
            "model": "claude-sonnet-4-6",
            "stop_reason": "end_turn",
            "usage": {"input_tokens": 10, "output_tokens": 5},
        }
    ).encode()

    mock_body = MagicMock()
    mock_body.read.return_value = body_bytes
    return {"body": mock_body}


@pytest.fixture()
def canned_bedrock_response():
    """Return a factory that produces canned Bedrock invoke_model responses."""
    return _make_canned_response


@pytest.fixture()
def mock_boto3_client(canned_bedrock_response):
    """Patch boto3.Session so no real AWS calls are made.

    The patched client's invoke_model returns a canned Anthropic-format response.
    """
    mock_client = MagicMock()
    mock_client.invoke_model.return_value = canned_bedrock_response()

    mock_session = MagicMock()
    mock_session.client.return_value = mock_client

    with patch("boto3.Session", return_value=mock_session) as patched_session:
        yield patched_session, mock_session, mock_client
