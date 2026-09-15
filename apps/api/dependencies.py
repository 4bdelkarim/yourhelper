"""Dépendances FastAPI.

Contient :
  - le provider du use case (injection de dépendance, point unique de câblage) ;
  - le mapping des exceptions réellement levées par le pipeline RAG vers des
    erreurs HTTP structurées — basé sur le code réel :
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

from apps.api.application.chat.chat_use_case import execute_chat


def get_chat_use_case():
    """Provider du use case — la route ne câble jamais le pipeline elle-même."""
    return execute_chat


def map_pipeline_exception(exc: Exception) -> HTTPException:
    """Traduit une exception du pipeline en erreur HTTP structurée.

    L'ordre des tests suit la précision du message : d'abord l'index (RuntimeError
    de get_collection / FileNotFoundError de load_parents), puis les erreurs
    Ollama explicites, puis les erreurs réseau génériques.
    """
    message = str(exc)

    # Index ChromaDB absent (RuntimeError de get_collection) ou parents manquants
    # (FileNotFoundError de load_parents) -> configuration serveur, pas la faute du client.
    if isinstance(exc, FileNotFoundError) or "Collection Chroma" in message:
        return HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "index_unavailable",
                "message": "L'index du corpus n'est pas disponible. "
                           "Lancez d'abord : make ingest DIR=data/normalized",
            },
        )

    # Modèle Ollama absent (RuntimeError explicite de llm_client.chat)
    if isinstance(exc, RuntimeError) and "n'est pas disponible" in message:
        return HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"code": "model_unavailable", "message": message},
        )

    # Ollama injoignable ou erreur du serveur de génération
    if isinstance(exc, (ollama.RequestError, ollama.ResponseError, httpx.HTTPError)):
        return HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"code": "ollama_unreachable",
                    "message": "Le serveur Ollama est injoignable ou en erreur."},
        )

    # Inconnue : ne pas exposer le détail interne au client.
    return HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail={"code": "internal_error", "message": "Erreur interne du tuteur."},
    )
