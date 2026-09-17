"""Dépendances FastAPI.

Contient :
  - les providers du use case (injection de dépendance, point unique de câblage) :
    execute_chat (JSON) et chat_events (SSE) ;
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

import httpx  # noqa: F401  (réexport pour compat : map_pipeline_exception vivait ici)
import ollama  # noqa: F401

from apps.api.application.chat.chat_use_case import chat_events, execute_chat
from apps.api.errors import map_pipeline_exception  # noqa: F401  (réexport)


def get_chat_use_case():
    """Provider du use case JSON — la route ne câble jamais le pipeline elle-même."""
    return execute_chat


def get_chat_events():
    """Provider du générateur d'événements SSE (POST /api/chat/stream)."""
    return chat_events
