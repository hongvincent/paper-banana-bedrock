"""AWS Bedrock client wrapping boto3 with async support and retry logic."""

import asyncio
import json
import logging
import os
import random
import time

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)

_RETRYABLE_ERRORS = {
    "ThrottlingException",
    "ModelTimeoutException",
    "ServiceUnavailableException",
    "InternalServerException",
}


class BedrockInvocationError(Exception):
    """Raised when a Bedrock invocation fails after all retries."""

    def __init__(self, message: str, cause: Exception | None = None):
        super().__init__(message)
        self.__cause__ = cause


class BedrockClient:
    """Thin async wrapper around the boto3 bedrock-runtime client."""

    def __init__(
        self,
        region: str | None = None,
        profile: str | None = None,
        model_id: str | None = None,
    ):
        self.region = region or os.environ.get("AWS_REGION", "ap-northeast-2")
        self.profile = profile or os.environ.get("AWS_PROFILE") or None
        self.model_id = model_id or os.environ.get(
            "BEDROCK_MODEL_ID", "global.anthropic.claude-sonnet-4-6"
        )
        self._max_tokens_default = int(os.environ.get("BEDROCK_MAX_TOKENS", "4096"))
        self._temperature_default = float(os.environ.get("BEDROCK_TEMPERATURE", "0.7"))

        session = boto3.Session(profile_name=self.profile)
        self._client = session.client("bedrock-runtime", region_name=self.region)

    def _build_body(
        self,
        messages: list[dict],
        max_tokens: int,
        temperature: float | None,
        system: str | None,
        top_p: float | None,
    ) -> dict:
        body: dict = {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": max_tokens,
            "messages": messages,
        }
        # Claude Sonnet 4.6 on Bedrock rejects temperature + top_p together.
        # Prefer temperature; only send top_p if the caller explicitly opts out
        # of temperature (temperature is None).
        if temperature is not None:
            body["temperature"] = temperature
        elif top_p is not None:
            body["top_p"] = top_p
        if system:
            body["system"] = system
        return body

    def _invoke_sync(self, model_id: str, body: dict) -> dict:
        response = self._client.invoke_model(
            modelId=model_id,
            body=json.dumps(body),
            contentType="application/json",
            accept="application/json",
        )
        raw = response["body"].read()
        return json.loads(raw)

    async def invoke_text(
        self,
        messages: list[dict],
        *,
        max_tokens: int | None = None,
        temperature: float | None = None,
        system: str | None = None,
        top_p: float | None = None,
    ) -> dict:
        """Invoke the Bedrock model and return the raw response dict.

        Returns a dict with keys: content, stop_reason, usage.
        Retries on transient errors with exponential backoff + jitter.
        """
        resolved_max_tokens = max_tokens if max_tokens is not None else self._max_tokens_default
        # Pass temperature through only if caller set it OR env default is set.
        # Bedrock rejects temperature + top_p together, so top_p is only used
        # when temperature is explicitly None and top_p is provided.
        if temperature is not None:
            resolved_temperature = temperature
            resolved_top_p = None
        elif top_p is not None:
            resolved_temperature = None
            resolved_top_p = top_p
        else:
            resolved_temperature = self._temperature_default
            resolved_top_p = None

        body = self._build_body(
            messages=messages,
            max_tokens=resolved_max_tokens,
            temperature=resolved_temperature,
            system=system,
            top_p=resolved_top_p,
        )

        max_retries = 3
        base_delay = 1.0
        last_exc: Exception | None = None

        for attempt in range(max_retries + 1):
            try:
                result = await asyncio.to_thread(self._invoke_sync, self.model_id, body)
                return result
            except ClientError as exc:
                error_code = exc.response.get("Error", {}).get("Code", "")
                if error_code in _RETRYABLE_ERRORS and attempt < max_retries:
                    delay = base_delay * (2 ** attempt) + random.uniform(0, 0.5)
                    logger.warning(
                        "Bedrock %s on attempt %d; retrying in %.2fs",
                        error_code,
                        attempt + 1,
                        delay,
                    )
                    await asyncio.sleep(delay)
                    last_exc = exc
                    continue
                last_exc = exc
                break
            except Exception as exc:
                last_exc = exc
                break

        raise BedrockInvocationError(
            f"Bedrock invocation failed after {max_retries + 1} attempts: {last_exc}",
            cause=last_exc,
        )
