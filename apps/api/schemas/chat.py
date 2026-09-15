"""Schemas Pydantic du contrat API /chat.

Contraire d'invention : ces modèles reflètent EXACTEMENT les structures réelles
du RAG existant —
  - RAGResult (src/rag_tutor/core/pipeline.py)
  - hits[*]["meta"] (src/rag_tutor/core/retriever.py, children_to_parents)
  - libellés de citation produits par generator.citation_label()

Tous les champs de Source sont optionnels à None car les métadonnées réelles
diffèrent selon source_type : les documents web portent source_url/title,
les PDF portent source_id/pages, jamais l'inverse. On n'invente rien.
"""

from pydantic import BaseModel, Field

# history : tours de conversation passés par le frontend (aucune persistance
# serveur au prototype — le frontend est seul responsable de l'historique).
# Mapping réel vers le pipeline : user -> "Étudiant", assistant -> "Tuteur"
# (format attendu par ConversationMemory / prompts du pipeline).


class HistoryTurn(BaseModel):
    role: str = Field(pattern="^(user|assistant)$", description="user=étudiant, assistant=tuteur")
    content: str = Field(min_length=1)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    conversation_id: str | None = Field(default=None, max_length=64)
    history: list[HistoryTurn] = Field(default_factory=list, max_length=40)
    # Nombre de passages récupérés — défaut identique au CLI (rag-chat --k 4).
    # Cap à 8 : chaque parent fait jusqu'à ~80K caractères, inutile de saturer
    # le contexte (NUM_CTX=24576) et la latence pour un prototype.
    k: int = Field(default=4, ge=1, le=8)


class Source(BaseModel):
    """Source réellement récupérée par le retrieval (un hit = une section parente).

    - label : libellé de citation complet produit par generator.citation_label()
      (ex : "web · d2l.ai · « 11.7. The Transformer Architecture » · §11.7.4. Encoder")
    - score : score du reranker (hybrid_rerank) — brut, non interprété côté API.
    """

    label: str
    source: str
    source_type: str | None = None
    source_url: str | None = None
    title: str | None = None
    source_id: str | None = None
    section: str | None = None
    page_start: int | None = None
    page_end: int | None = None
    score: float | None = None


class ChatResponse(BaseModel):
    conversation_id: str
    answer: str
    refused: bool
    sources: list[Source]
    meta: dict = Field(
        default_factory=dict,
        description="Informations réelles disponibles dans RAGResult : "
        "rewritten_query, sub_queries, latency_ms.",
    )
