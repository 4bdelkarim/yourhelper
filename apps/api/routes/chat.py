"""Routes de chat — POST /api/chat (JSON) et POST /api/chat/stream (SSE).

Adaptateurs HTTP minimaux : validation Pydantic -> use case -> réponse/flux.
Aucune logique RAG ici.

Découpage du flux SSE (dicté par le pipeline, cf. chat_use_case.chat_events) :
  - la phase bloquante (query processing + retrieval + refus M1, 15-30 s) est
    exécutée AVANT l'envoi des en-têtes : une erreur à ce stade reste une
    HTTPException 5xx/422 classique, consommable comme une erreur REST ;
  - ensuite, StreamingResponse émet meta -> token* -> done | error.

Handlers `def` (pas async def) : FastAPI les exécute dans son threadpool
(anyio), donc le pipeline bloquant (appels Ollama, cross-encoder CPU, BM25)
ne gèle jamais l'event loop — /health et les autres requêtes restent servis
pendant une génération de 30-90 s. Une route `async def` qui appellerait le
pipeline directement bloquerait TOUT le serveur.

IMPORTANT — un seul worker Uvicorn : ChromaDB est un client embarqué sur un
chemin partagé (chroma_db/), cf. audit §12. Ne PAS lancer avec --workers N.
"""

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from apps.api.dependencies import get_chat_events, get_chat_use_case
from apps.api.errors import map_pipeline_exception
from apps.api.schemas.chat import ChatRequest, ChatResponse
from apps.api.sse import sse_lines

router = APIRouter()

MEDIA_TYPE_SSE = "text/event-stream"
# X-Accel-Buffering: no → anti-buffering déjà en place si un reverse proxy
# (nginx, phase 7) est ajouté devant la route ; sans effet sinon.
SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}


@router.post("/chat", response_model=ChatResponse)
def chat(request: ChatRequest, use_case=Depends(get_chat_use_case)) -> ChatResponse:
    """Question -> réponse complète (JSON)."""
    try:
        return use_case(request)
    except Exception as exc:
        raise map_pipeline_exception(exc) from exc


@router.post("/chat/stream")
def chat_stream(request: ChatRequest, events=Depends(get_chat_events)) -> StreamingResponse:
    """Question -> flux SSE : event meta (sources) puis token* puis done|error."""
    return StreamingResponse(
        sse_lines(events(request)),
        media_type=MEDIA_TYPE_SSE,
        headers=SSE_HEADERS,
    )
