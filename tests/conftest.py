"""Fixtures partagées des tests API — le RAG est simulé, TOUT le reste est réel.

Seam choisi : `pipeline_answer` est remplacé DANS LE NAMESPACE du use case
(`apps.api.application.chat.chat_use_case`), là où `execute_chat()` et
`chat_events()` l'appellent réellement. Les tests exercent donc :
  - les routes FastAPI (validation, mapping d'erreurs, StreamingResponse) ;
  - les schémas Pydantic (contrat Request/Response) ;
  - format_history() (sérialisation pour la résolution des anaphores) ;
  - le mapping hits -> sources (citation_label) ;
  - le mapping exceptions -> erreurs structurées.

Seul le RAG (Ollama, ChromaDB, reranker) est simulé : aucun réseau, aucun
modèle, aucune base — la suite tourne en quelques secondes et peut passer en CI.
"""

import json

import pytest
from fastapi.testclient import TestClient

import apps.api.application.chat.chat_use_case as chat_use_case
from apps.api.main import app

REFUSAL = "Les documents fournis ne permettent pas de répondre à cette question."


def make_hit(
    text: str = "La cellule LSTM introduit des portes de contrôle du gradient.",
    score: float = 0.82,
    meta: dict | None = None,
) -> dict:
    """Un hit au format EXACT de retriever.children_to_parents() (PDF par défaut)."""
    if meta is None:
        meta = {
            "source": "05_RNN",
            "source_type": "pdf",
            "source_url": None,
            "title": None,
            "source_id": "05_RNN.pdf",
            "page": 4,
            "page_start": 4,
            "page_end": 5,
            "section": "3.1- LSTM",
            "parent_id": "05_RNN__sec001",
        }
    return {"text": text, "dist": score, "meta": meta}


def make_web_hit() -> dict:
    """Variante web — les métadonnées réelles diffèrent des PDF (url + titre, pas de pages)."""
    return make_hit(
        meta={
            "source": "chapter_recurrent-modern_lstm",
            "source_type": "web",
            "source_url": "https://d2l.ai/chapter_recurrent-modern/lstm.html",
            "title": "10.1. Long Short-Term Memory (LSTM)",
            "source_id": None,
            "page": None,
            "page_start": None,
            "page_end": None,
            "section": "10.1. Long Short-Term Memory (LSTM)",
            "parent_id": "lstm__sec010",
        },
        score=0.86,
    )


class FailingStream:
    """Itérable de tokens qui yield ceux fournis puis lève l'exception donnée."""

    def __init__(self, tokens: list[str], exc: Exception):
        self._tokens, self._exc = tokens, exc

    def __iter__(self):
        yield from self._tokens
        raise self._exc


class FakeResult:
    """Double de RAGResult — mêmes champs publics, consommé par le use case.

    stream=None -> mode non-stream (JSON) ; stream=list[str] | FailingStream ->
    mode stream (SSE).
    """

    def __init__(self, *, hits: list[dict], answer: str = "",
                 refused: bool = False, stream=None):
        self.query = "question brute"
        self.rewritten_query = "question reformulée"
        self.sub_queries = []
        self.hits = hits
        self.contexts = [h["text"] for h in hits]
        self.answer = answer
        self.refused = refused
        self.answer_stream = iter(stream) if stream is not None else None


@pytest.fixture
def client():
    """TestClient — raise_server_exceptions=False : les erreurs sont testées
    via les réponses HTTP, comme un client réel."""
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


@pytest.fixture
def fake_pipeline(monkeypatch):
    """Remplace pipeline.answer dans le namespace du use case.

    Usage :
        fake_pipeline(FakeResult(hits=[...], stream=[...]))   # résultat fixe
        fake_pipeline(RuntimeError("Collection Chroma ..."))  # exception à lever

    La fonction installée trace ses appels dans .calls pour les assertions
    du contrat (history, k, stream, message transmis).
    """

    def install(behavior):
        def _answer(query, **kwargs):
            _answer.calls.append((query, kwargs))
            if isinstance(behavior, Exception):
                raise behavior
            return behavior

        _answer.calls = []
        monkeypatch.setattr(chat_use_case, "pipeline_answer", _answer)
        return _answer

    return install


@pytest.fixture
def parse_sse():
    """Parse un corps text/event-stream en [(event, charge dict), ...].

    Découpage identique à celui du client frontend (blocs séparés par \\n\\n,
    préfixes event:/data:) — les tests valident donc le format filaire réel.
    """

    def _parse(body: str) -> list[tuple[str, dict]]:
        events: list[tuple[str, dict]] = []
        for block in body.split("\n\n"):
            block = block.strip()
            if not block:
                continue
            event, data = None, None
            for line in block.split("\n"):
                if line.startswith("event:"):
                    event = line[len("event:"):].strip()
                elif line.startswith("data:"):
                    data = line[len("data:"):].strip()
            if event is not None and data is not None:
                events.append((event, json.loads(data)))
        return events

    return _parse
