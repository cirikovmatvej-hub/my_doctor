"""
Regression test: the Groq client must have an explicit, above-default
max_retries so transient 429/5xx/connection failures get the SDK's built-in
exponential-backoff retry instead of silently relying on the openai
library's unconfigured default (2), which nobody reviewing this file would
otherwise notice is even happening.
"""
from ai.assistant import client
from config import GROQ_MAX_RETRIES


def test_client_has_explicit_above_default_max_retries():
    assert client.max_retries == GROQ_MAX_RETRIES
    assert client.max_retries > 2  # openai's own unconfigured default
