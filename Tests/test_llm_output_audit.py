import sqlite3
import pytest
from Core.exceptions import ProviderError
from Providers.base_provider import BaseProvider
from Providers.response import ProviderResponse, Usage
from Services.copilot_explanation_service import CopilotExplanationResult
from Services.copilot_explanation_llm_narrator import narrate_explanation
from Services.llm_output_audit_hook import record_llm_output, prompt_hash
from Providers.message import Message, MessageRole

class FakeProvider(BaseProvider):
    def __init__(self, text, model="fake-model", error=None):
        super().__init__()
        self.text = text
        self.model = model
        self.error = error
    
    @property
    def name(self) -> str:
        return self.model
        
    def generate(self, messages, **kwargs):
        if self.error: raise self.error
        return ProviderResponse(
            text=self.text,
            model=self.model,
            usage=Usage(total_tokens=42)
        )
    
    def health_check(self) -> bool: return True
    def connect(self): pass
    def disconnect(self): pass
    def stream(self, messages, **kwargs): raise NotImplementedError
    def count_tokens(self, messages): return 0

class FakeRepo:
    def __init__(self):
        self.rows = []
    
    def create(self, timestamp, model, prompt_hash, source_data, response, tokens, latency_ms):
        self.rows.append({
            "timestamp": timestamp,
            "model": model,
            "prompt_hash": prompt_hash,
            "source_data": source_data,
            "response": response,
            "tokens": tokens,
            "latency_ms": latency_ms
        })
        return len(self.rows)

def test_prompt_hash_stable():
    msgs = [Message(role=MessageRole.SYSTEM, content="sys"), Message(role=MessageRole.USER, content="hi")]
    h1 = prompt_hash(msgs)
    h2 = prompt_hash(msgs)
    assert h1 == h2
    assert len(h1) == 64

def test_record_inserts_row():
    repo = FakeRepo()
    msgs = [Message(role=MessageRole.USER, content="test")]
    row_id = record_llm_output(
        repo,
        model="test-model",
        messages=msgs,
        response_text="output",
        source_data="source",
        tokens=10,
        latency_ms=50
    )
    assert row_id == 1
    assert len(repo.rows) == 1
    assert repo.rows[0]["model"] == "test-model"
    assert repo.rows[0]["response"] == "output"
    assert repo.rows[0]["tokens"] == 10

def test_narrate_with_audit():
    repo = FakeRepo()
    res = CopilotExplanationResult(
        success=True, status="SUCCESS", title="T", summary="base summary", reason="r"
    )
    provider = FakeProvider("LLM output")
    out = narrate_explanation(res, provider, audit_repository=repo, source_data="raw")
    assert out == "LLM output"
    assert len(repo.rows) == 1
    assert repo.rows[0]["source_data"] == "raw"

def test_narrate_no_repo():
    res = CopilotExplanationResult(
        success=True, status="SUCCESS", title="T", summary="base", reason="r"
    )
    provider = FakeProvider("LLM")
    out = narrate_explanation(res, provider, audit_repository=None)
    assert out == "LLM"

def test_narrate_provider_error_fallback():
    repo = FakeRepo()
    res = CopilotExplanationResult(
        success=True, status="SUCCESS", title="T", summary="fallback", reason="r"
    )
    provider = FakeProvider("", error=ProviderError("fail"))
    out = narrate_explanation(res, provider, audit_repository=repo)
    assert out == "fallback"
    assert len(repo.rows) == 0
