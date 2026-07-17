"""Tests for api.main — the FastAPI app. No real Groq/Chroma calls.

rewrite_query, translate_to_english, retrieve, and generate_answer are all
patched at the api.main module level (where they're imported into), so
these tests only verify the endpoint wiring, not the underlying logic —
each of those has its own dedicated test module.
"""

from __future__ import annotations

from unittest.mock import patch

from fastapi.testclient import TestClient

from api.main import app

client = TestClient(app)


def test_chat_pipeline_calls_rewrite_translate_retrieve_generate_in_order():
    with patch("api.main.rewrite_query", return_value="standalone question") as mock_rewrite, \
         patch("api.main.translate_to_english", return_value="english question") as mock_translate, \
         patch("api.main.retrieve", return_value=[{"score": -0.03, "vector_distance": 5.0, "metadata": {}, "text": "x"}]) as mock_retrieve, \
         patch("api.main.generate_answer", return_value={"answer": "an answer", "refused": False, "citations": []}) as mock_generate:
        response = client.post("/chat", json={"message": "how much leave do I get?", "history": []})

    assert response.status_code == 200
    body = response.json()
    assert body == {"answer": "an answer", "refused": False, "citations": []}

    mock_rewrite.assert_called_once_with("how much leave do I get?", [])
    mock_translate.assert_called_once_with("standalone question")
    mock_retrieve.assert_called_once()
    assert mock_retrieve.call_args.args[0] == "english question"
    mock_generate.assert_called_once()
    assert mock_generate.call_args.args[0] == "english question"


def test_chat_passes_act_filter_through_to_retrieve():
    with patch("api.main.rewrite_query", return_value="q"), \
         patch("api.main.translate_to_english", return_value="q"), \
         patch("api.main.retrieve", return_value=[]) as mock_retrieve, \
         patch("api.main.generate_answer", return_value={"answer": "x", "refused": True, "citations": []}):
        client.post("/chat", json={
            "message": "q", "history": [],
            "act_filter": "Sindh Shops and Commercial Establishments Act",
        })

    assert mock_retrieve.call_args.kwargs.get("act_name") == "Sindh Shops and Commercial Establishments Act"


def test_acts_endpoint_returns_sorted_distinct_act_names():
    fake_collection = type("FakeCollection", (), {
        "get": lambda self, include: {
            "metadatas": [
                {"act_name": "Sindh Shops and Commercial Establishments Act"},
                {"act_name": "Sindh Minimum Wages Act"},
                {"act_name": "Sindh Shops and Commercial Establishments Act"},
            ]
        }
    })()
    fake_client = type("FakeClient", (), {"get_collection": lambda self, name: fake_collection})()

    with patch("chromadb.PersistentClient", return_value=fake_client):
        response = client.get("/acts")

    assert response.status_code == 200
    assert response.json() == {
        "acts": ["Sindh Minimum Wages Act", "Sindh Shops and Commercial Establishments Act"]
    }


def test_health_endpoint_reports_chunk_count():
    fake_collection = type("FakeCollection", (), {"count": lambda self: 235})()
    fake_client = type("FakeClient", (), {"get_collection": lambda self, name: fake_collection})()

    with patch("chromadb.PersistentClient", return_value=fake_client):
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "chunks_indexed": 235}
