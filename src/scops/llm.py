"""LLM access: mock (offline) | databricks (Model Serving, OpenAI-compatible) | azure | openai."""
from __future__ import annotations

import json
import os
import re
from functools import lru_cache


def provider() -> str:
    return os.getenv("LLM_PROVIDER", "mock").lower()


@lru_cache
def _client():
    p = provider()
    if p == "databricks":
        from openai import OpenAI
        return OpenAI(base_url=os.environ["DATABRICKS_HOST"].rstrip("/") + "/serving-endpoints",
                      api_key=os.environ["DATABRICKS_TOKEN"]), os.getenv("LLM_MODEL", "databricks-meta-llama-3-3-70b-instruct")
    if p == "azure":
        from openai import AzureOpenAI
        return AzureOpenAI(azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"], api_key=os.environ["AZURE_OPENAI_API_KEY"],
                           api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2024-10-21")), os.environ["AZURE_OPENAI_DEPLOYMENT"]
    from openai import OpenAI
    return OpenAI(), os.getenv("LLM_MODEL", "gpt-4.1-mini")


def complete_json(system: str, user: str) -> dict:
    client, model = _client()
    resp = client.chat.completions.create(model=model, temperature=0, messages=[
        {"role": "system", "content": system}, {"role": "user", "content": user}])
    text = resp.choices[0].message.content or "{}"
    m = re.search(r"\{.*\}", text, re.DOTALL)
    return json.loads(m.group(0)) if m else {}
