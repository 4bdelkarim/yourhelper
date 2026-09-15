"""Route POST /api/chat — adaptateur HTTP minimal autour du use case.

Aucune logique RAG ici : validation (schemas Pydantic) -> use case -> réponse.

`def` et non `async def` : le handler synchrone est exécuté par FastAPI dans
son threadpool (anyio), donc le pipeline bloquant (appels Ollama, cross-encoder
CPU, BM25) ne gèle jamais l'event loop — pendant ce temps, /health et les
autres requêtes restent servis. Une route `async def` qui appellerait le
pipeline directement bloquerait TOUT le serveur pendant 30-90 s.
"""

from fastapi import APIRouter, Depends, Request

from apps.api.dependencies import get_chat_use_case, map_pipeline_exception
from apps.api.schemas.chat import ChatRequest, ChatResponse

router = APIRouter()


@router.post("/chat", response_model=ChatResponse)
def chat(request: ChatRequest, use_case=Depends(get_chat_use_case)) -> ChatResponse:
    try:
        return use_case(request)
    except Exception as exc:
        raise map_pipeline_exception(exc) from exc
