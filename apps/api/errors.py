"""Mapping des exceptions du pipeline vers des erreurs structurées.

Refactor SANS changement de comportement de la route JSON : le contenu de
map_pipeline_exception() est déplacé ici depuis dependencies.py pour être
réutilisable par le flux SSE (où les erreurs deviennent des événements
`event: error` plutôt que des HTTPException).

Correspond au code réel du RAG :
  * vector_store.get_collection() -> RuntimeError ("Collection Chroma ... introuvable")
  * vector_store.load_parents()   -> FileNotFoundError (parents_*.json absent)
  * llm_client.chat()             -> RuntimeError ("Le modele Ollama '<m>' n'est pas disponible")
                                     ou re-raise des erreurs réseau/client Ollama
  * embeddings.embed_query()      -> erreurs client Ollama (pas de retry sur la requête)
  * process_query / verify_answer / should_refuse_reranker -> ne lèvent jamais
    (fallbacks internes assumés par le RAG existant)
"""

import httpx
import ollama
from fastapi import HTTPException, status


def error_payload(exc: Exception) -> tuple[int, str, str]:
    """Classifie une exception du pipeline en (status HTTP, code, message).

    L'ordre des tests suit la précision du message : d'abord l'index
    (RuntimeError de get_collection / FileNotFoundError de load_parents),
    puis les erreurs Ollama explicites, puis les erreurs réseau génériques.
    """
    message = str(exc)

    # Index ChromaDB absent (RuntimeError de get_collection) ou parents manquants
    # (FileNotFoundError de load_parents) -> configuration serveur, pas la faute du client.
    if isinstance(exc, FileNotFoundError) or "Collection Chroma" in message:
        return status.HTTP_503_SERVICE_UNAVAILABLE, "index_unavailable", (
            "L'index du corpus n'est pas disponible. "
            "Lancez d'abord : make ingest DIR=data/normalized"
        )

    # Modèle Ollama absent (RuntimeError explicite de llm_client.chat)
    if isinstance(exc, RuntimeError) and "n'est pas disponible" in message:
        return status.HTTP_502_BAD_GATEWAY, "model_unavailable", message

    # Ollama injoignable ou erreur du serveur de génération
    if isinstance(exc, (ollama.RequestError, ollama.ResponseError, httpx.HTTPError)):
        return status.HTTP_502_BAD_GATEWAY, "ollama_unreachable", (
            "Le serveur Ollama est injoignable ou en erreur."
        )

    # Inconnue : ne pas exposer le détail interne au client.
    return status.HTTP_500_INTERNAL_SERVER_ERROR, "internal_error", "Erreur interne du tuteur."


def map_pipeline_exception(exc: Exception) -> HTTPException:
    """Traduit une exception du pipeline en erreur HTTP structurée."""
    status_code, code, message = error_payload(exc)
    return HTTPException(status_code=status_code, detail={"code": code, "message": message})
