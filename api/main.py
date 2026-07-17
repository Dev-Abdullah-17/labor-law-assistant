"""FastAPI app: POST /chat, GET /health.

Usage: uvicorn api.main:app --reload
"""

from __future__ import annotations

from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from api.generate import generate_answer
from api.rewrite import rewrite_query, translate_to_english
from retrieval.index import CHROMA_DIR, COLLECTION_NAME
from retrieval.query import query as retrieve

app = FastAPI(title="Labor Law Assistant API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatTurn(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    message: str
    history: list[ChatTurn] = []
    act_filter: str | None = None


class ChatResponse(BaseModel):
    answer: str
    refused: bool
    citations: list[dict]


@app.post("/chat", response_model=ChatResponse)
def chat(request: ChatRequest) -> ChatResponse:
    history = [turn.model_dump() for turn in request.history]
    standalone_question = rewrite_query(request.message, history)
    # Roman Urdu / Urdu queries retrieve poorly against this English-only
    # corpus even in proper Urdu script (see PROGRESS.md, Milestone 5) —
    # translating to English before retrieval is what actually fixes it,
    # not hybrid search alone. English input passes through unchanged.
    english_question = translate_to_english(standalone_question)
    hits = retrieve(english_question, act_name=request.act_filter)
    result = generate_answer(english_question, hits)
    return ChatResponse(**result)


@app.get("/acts")
def list_acts() -> dict:
    """Distinct act names actually in the index, for the UI's filter dropdown."""
    try:
        import chromadb

        client = chromadb.PersistentClient(path=str(CHROMA_DIR))
        collection = client.get_collection(COLLECTION_NAME)
        records = collection.get(include=["metadatas"])
        acts = sorted({m["act_name"] for m in records["metadatas"] if m.get("act_name")})
        return {"acts": acts}
    except Exception as exc:
        return JSONResponse(status_code=503, content={"status": "error", "detail": str(exc)})


@app.get("/health")
def health():
    try:
        import chromadb

        client = chromadb.PersistentClient(path=str(CHROMA_DIR))
        collection = client.get_collection(COLLECTION_NAME)
        count = collection.count()
        return {"status": "ok", "chunks_indexed": count}
    except Exception as exc:
        return JSONResponse(status_code=503, content={"status": "error", "detail": str(exc)})
