"""chat_use_case — logique applicative du chat.

SEUL endroit qui connaît à la fois :
  - le contrat API (apps.api.schemas.chat)
  - le point d'entrée RAG (rag_tutor.core.pipeline.answer)

La route FastAPI n'appelle QUE ce module : elle ne connaît ni le retrieval,
ni le reranker, ni les prompts, ni Chroma.

Historique : le pipeline attend une chaîne pré-formatée (str | None), au format
produit par ConversationMemory.get_formatted_history() — cf. cli/tutor.py :
    [DERNIERS ÉCHANGES]
    Étudiant : ...
    Tuteur : ...
Cette chaîne est injectée telle quelle dans les prompts du query processing
(résolution des anaphores) et du générateur. Le frontend envoie les tours
précédents (SANS le message courant, déjà passé comme `query` — dans le CLI
la question courante est dans l'historique parce qu'elle est ajoutée AVANT
l'appel ; côté API la passer deux fois dupliquerait la question dans le prompt).
"""

import time
import uuid

from rag_tutor.core.generator import citation_label
from rag_tutor.core.pipeline import RAGResult, answer as pipeline_answer

from apps.api.schemas.chat import ChatRequest, ChatResponse, Source

_ROLE_LABELS = {"user": "Étudiant", "assistant": "Tuteur"}


def format_history(history: list[dict]) -> str | None:
    """Sérialise l'historique frontend au format attendu par le pipeline.

    Retourne None si l'historique est vide (mode Q&A direct, comportement
    historique du pipeline inchangé).
    """
    if not history:
        return None
    lines = ["[DERNIERS ÉCHANGES]"]
    for turn in history:
        role = _ROLE_LABELS.get(turn["role"], turn["role"])
        lines.append(f"{role} : {turn['content']}")
    return "\n".join(lines)


def _to_source(hit: dict) -> Source:
    """Mappe un hit réel du retriever vers le schéma Source.

    Le label vient exclusivement de citation_label() (libellé de citation
    existant, déjà utilisé par les CLI) — aucune URL/titre/section inventés.
    """
    meta = hit.get("meta") or {}
    return Source(
        label=citation_label(meta),
        source=meta.get("source", ""),
        source_type=meta.get("source_type"),
        source_url=meta.get("source_url"),
        title=meta.get("title"),
        source_id=meta.get("source_id"),
        section=meta.get("section"),
        page_start=meta.get("page_start"),
        page_end=meta.get("page_end"),
        score=hit.get("dist"),
    )


def _to_response(result: RAGResult, conversation_id: str, latency_ms: int) -> ChatResponse:
    """Mappe le RAGResult réel vers le contrat API."""
    return ChatResponse(
        conversation_id=conversation_id,
        answer=result.answer,
        refused=result.refused,
        sources=[_to_source(h) for h in result.hits],
        meta={
            "rewritten_query": result.rewritten_query,
            "sub_queries": result.sub_queries,
            "latency_ms": latency_ms,
        },
    )


def execute_chat(request: ChatRequest) -> ChatResponse:
    """Exécute le pipeline RAG existant et mappe le résultat au contrat API.

    Fonction SYNCHRONE volontairement : appelée depuis une route FastAPI `def`,
    elle s'exécute dans le threadpool de Starlette et ne bloque jamais
    l'event loop (le pipeline est bloquant : Ollama, cross-encoder).
    """
    conversation_id = request.conversation_id or str(uuid.uuid4())
    history = format_history([t.model_dump() for t in request.history])

    t0 = time.perf_counter()
    result = pipeline_answer(
        request.message,
        k=request.k,
        history=history,
        stream=False,
    )
    latency_ms = int((time.perf_counter() - t0) * 1000)

    return _to_response(result, conversation_id, latency_ms)
