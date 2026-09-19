"""Ollama backend/embedder tests — no server needed, a fake transport stands in."""

from arius.config import AriusConfig, UserConfig
from arius.core import Arius
from arius.embeddings import OllamaEmbedder, build_embedder
from arius.llm import build_backend
from arius.llm.base import Message
from arius.llm.ollama_backend import OllamaBackend
from arius.memory import Memory
from arius.ollama import has_model, probe


def fake_transport(models=("llama3.1:latest",), reply="안녕하십니까, 오너님.", legacy_embed=False):
    calls = []

    def _t(method, path, payload, timeout):
        calls.append((method, path, payload))
        if path == "/api/tags":
            return {"models": [{"name": m} for m in models]}
        if path == "/api/chat":
            return {"message": {"role": "assistant", "content": reply}}
        if path == "/api/embed":
            if legacy_embed:
                raise RuntimeError("404 not found")
            return {"embeddings": [[3.0, 4.0, 0.0] for _ in payload["input"]]}
        if path == "/api/embeddings":
            return {"embedding": [0.0, 0.0, 2.0]}
        raise AssertionError(f"unexpected path {path}")

    _t.calls = calls
    return _t


def down_transport(method, path, payload, timeout):
    raise ConnectionRefusedError("connection refused")


# --- helpers ---------------------------------------------------------------


def test_has_model_matches_tags():
    names = {"llama3.1:latest", "exaone3.5:7.8b"}
    assert has_model(names, "llama3.1")
    assert has_model(names, "llama3.1:latest")
    assert has_model(names, "exaone3.5")
    assert not has_model(names, "exaone3.5:2.4b")  # explicit tag must match exactly
    assert not has_model(names, "qwen2.5")


def test_probe_reports_server_down_and_missing_model():
    assert "연결할 수 없습니다" in probe(down_transport, "llama3.1", "http://x")
    assert "ollama pull qwen2.5" in probe(fake_transport(), "qwen2.5", "http://x")
    assert probe(fake_transport(), "llama3.1", "http://x") is None


# --- chat backend ----------------------------------------------------------


def test_backend_generates_with_system_first_and_options():
    t = fake_transport()
    be = OllamaBackend(model="llama3.1", transport=t, temperature=0.2, max_tokens=99)
    assert be.available
    out = be.generate("당신은 ARIUS입니다.", [Message("user", "안녕")])
    assert out == "안녕하십니까, 오너님."
    method, path, payload = t.calls[-1]
    assert (method, path) == ("POST", "/api/chat")
    assert payload["model"] == "llama3.1" and payload["stream"] is False
    assert payload["messages"][0] == {"role": "system", "content": "당신은 ARIUS입니다."}
    assert payload["messages"][-1] == {"role": "user", "content": "안녕"}
    assert payload["options"] == {"temperature": 0.2, "num_predict": 99}


def test_backend_unavailable_when_model_not_pulled():
    be = OllamaBackend(model="qwen2.5", transport=fake_transport())
    assert not be.available
    assert "ollama pull qwen2.5" in be.unavailable_reason()


def test_build_backend_falls_back_to_echo_when_server_down():
    cfg = AriusConfig()
    cfg.llm.backend = "ollama"
    cfg.llm.base_url = "http://127.0.0.1:9"  # nothing listens here
    be = build_backend(cfg)
    assert be.name == "echo"
    assert "연결할 수 없습니다" in getattr(be, "_degraded_reason", "")


def test_arius_chat_routes_through_injected_ollama_backend():
    cfg = AriusConfig(users=[UserConfig("owner", "owner", "오너")])
    arius = Arius(cfg, memory=Memory(":memory:"), backend=OllamaBackend(transport=fake_transport()))
    arius.login("owner")
    reply = arius.handle("오늘 기분 어때?")
    assert reply.source == "llm:ollama"
    assert reply.text == "안녕하십니까, 오너님."


# --- embedder --------------------------------------------------------------


def test_ollama_embedder_normalizes_and_batches():
    t = fake_transport(models=("bge-m3:latest",))
    e = OllamaEmbedder("bge-m3", transport=t)
    assert e.name == "ollama:bge-m3" and e.dim == 3
    v = e.embed("테스트")
    assert abs(v[0] - 0.6) < 1e-6 and abs(v[1] - 0.8) < 1e-6  # [3,4,0] / 5
    many = e.embed_many(["a", "b", "c"])
    assert len(many) == 3
    assert t.calls[-1][2]["input"] == ["a", "b", "c"]  # one batched request


def test_ollama_embedder_falls_back_to_legacy_endpoint():
    t = fake_transport(models=("bge-m3:latest",), legacy_embed=True)
    e = OllamaEmbedder("bge-m3", transport=t)
    assert e.embed("x") == [0.0, 0.0, 1.0]
    assert any(p == "/api/embeddings" for _, p, _ in t.calls)


def test_build_embedder_falls_back_to_hashing_when_ollama_down():
    cfg = AriusConfig()
    cfg.embeddings.backend = "ollama"
    cfg.embeddings.base_url = "http://127.0.0.1:9"
    assert build_embedder(cfg).name == "hashing-v1"


def test_semantic_memory_works_with_ollama_embedder():
    e = OllamaEmbedder("bge-m3", transport=fake_transport(models=("bge-m3:latest",)))
    with Memory(":memory:", embedder=e) as mem:
        mem.learn_fact("owner", "취미", "슈트 제작")
        assert mem.index_size() == 1
        # fake vectors are identical, so anything semantic scores 1.0
        assert mem.recall_facts("owner", "아무거나")[0].key == "취미"
