"""Route GET /api/health — sonde de vie + diagnostic des dépendances.

Vérifie sans rien charger de lourd :
  - Ollama joignable et modèles requis présents (GET /api/tags, timeout court) ;
  - index Chroma présent (compte des enfants) ;
  - magasin de parents présent (fichier) ;
  - mode de retrieval et état du reranker, lus comme attributs de module
    SANS déclencher _lazy() (aucun chargement d'embedder/BM25/reranker).
"""

from fastapi import APIRouter
from fastapi.responses import JSONResponse

import requests

from rag_tutor.core import embeddings as embeddings_module
from rag_tutor.core import llm_client as llm_client_module
from rag_tutor.core import retriever as retriever_module
from rag_tutor.core import vector_store as vector_store_module

router = APIRouter()

OLLAMA_MODELS_REQUIRED = [llm_client_module.GEN_MODEL, "bge-m3"]
HEALTH_TIMEOUT_S = 2


def _check_ollama() -> dict:
    try:
        resp = requests.get(f"{llm_client_module.OLLAMA_HOST}/api/tags", timeout=HEALTH_TIMEOUT_S)
        resp.raise_for_status()
        names = [m.get("name", "") for m in resp.json().get("models", [])]
        missing = [m for m in OLLAMA_MODELS_REQUIRED if not any(n.startswith(m) for n in names)]
        return {"reachable": True, "models": names, "missing_models": missing}
    except requests.RequestException as exc:
        return {"reachable": False, "error": f"{type(exc).__name__}: {exc}"}


def _check_index() -> dict:
    try:
        coll = vector_store_module.get_collection()
        count = coll.count()
    except Exception as exc:
        return {"loaded": False, "error": str(exc).splitlines()[0]}
    parents_ok = vector_store_module._parents_path().exists()
    return {"loaded": count > 0, "children": count, "parents_file": parents_ok}


@router.get("/health")
def health() -> JSONResponse:
    ollama_state = _check_ollama()
    index_state = _check_index()

    ok = ollama_state["reachable"] and index_state["loaded"] and not ollama_state.get("missing_models")
    body = {
        "status": "ok" if ok else "degraded",
        "ollama": ollama_state,
        "index": index_state,
        "retrieval": {
            "mode": retriever_module.MODE,
            "reranker_active": retriever_module.RERANKER_ACTIVE,
        },
        "embedding_model": embeddings_module.EMBEDDING_MODEL,
    }
    # 200 même en "degraded" : /health est une sonde, pas une erreur applicative.
    return JSONResponse(status_code=200, content=body)
