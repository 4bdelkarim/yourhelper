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

Deux modes de sortie :
  - execute_chat()  : blocant, retourne ChatResponse (POST /api/chat) ;
  - chat_events()   : générateur d'événements SSE (POST /api/chat/stream).
Le contrat (conversation_id, sources, refus, reformulation) est IDENTIQUE
dans les deux modes.
"""

import time
import uuid
from collections.abc import Iterator

from rag_tutor.core.generator import citation_label
from rag_tutor.core.pipeline import RAGResult, answer as pipeline_answer

from apps.api.errors import error_payload
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


def chat_events(request: ChatRequest) -> Iterator[tuple[str, dict]]:
    """Générateur SYNCHRONE d'événements SSE pour POST /api/chat/stream.

    Contrat de flux (audit §8/§11) : meta -> token* -> done | error.

    Répartition temporelle dictée par le pipeline RAG existant :
      - pipeline_answer(stream=True) exécute AVANT de retourner toute la partie
        bloquante (query processing, retrieval, refus M1) : 15-30 s sans rien
        émettre. C'est pourquoi la route envoie les en-têtes HTTP seulement
        après cet appel : une erreur survenue dans cette phase reste une
        erreur HTTP 5xx propre, pas un flux déjà ouvert.
      - answer_stream est paresseux : chaque token est yield ici au fur et à
        mesure de la génération Ollama.
    """
    conversation_id = request.conversation_id or str(uuid.uuid4())
    history = format_history([t.model_dump() for t in request.history])

    t0 = time.perf_counter()
    # Phase bloquante (QP + retrieval + M1) : aucune exception ici ne doit
    # arriver après l'ouverture du flux — la route lève avant les en-têtes.
    result = pipeline_answer(
        request.message,
        k=request.k,
        history=history,
        stream=True,
    )

    if result.refused:
        # Refus M1 (seuil reranker) : decided avant generation, aucun token.
        yield "meta", _meta_payload(result, conversation_id, refused=True)
        yield "done", {"latency_ms": _elapsed_ms(t0)}
        return

    yield "meta", _meta_payload(result, conversation_id, refused=False)

    # Le streamer reconstruit la reponse complete en concatenant les tokens
    # (usage documente dans RAGResult.answer_stream). Garde-fou : si le
    # generateur du pipeline echoue, l'erreur devient un event `error` —
    # les en-tetes sont deja partis, on ne peut plus renvoyer un code HTTP.
    try:
        for token in result.answer_stream:
            if token:
                yield "token", {"delta": token}
    except Exception as exc:
        status_code, code, message = error_payload(exc)
        yield "error", {"code": code, "message": message, "status": status_code}
        return

    yield "done", {"latency_ms": _elapsed_ms(t0)}


def _meta_payload(result: RAGResult, conversation_id: str, refused: bool) -> dict:
    """Charge de l'event `meta` : conversation + sources + refus + reformulation.

    Sources construites exactement comme en mode JSON (_to_source), le client
    affiche donc les memes libelles citation_label() dans les deux modes.
    """
    return {
        "conversation_id": conversation_id,
        "refused": refused,
        "sources": [_to_source(h).model_dump() for h in result.hits],
        "rewritten_query": result.rewritten_query,
        "sub_queries": result.sub_queries,
    }


def _elapsed_ms(t0: float) -> int:
    return int((time.perf_counter() - t0) * 1000)
