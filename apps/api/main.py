"""Application FastAPI du tuteur RAG — couche applicative MINIMALE.

Le backend est un adaptateur autour du RAG existant :
    HTTP -> routes/chat.py -> application/chat/chat_use_case.py
         -> rag_tutor.core.pipeline.answer() -> ChromaDB + Ollama

Aucun composant du RAG n'est modifié ni réimplémenté ici.

Lancement (à la racine du projet, pour que chroma_db/ relatif soit résolu) :
    .venv/bin/uvicorn apps.api.main:app --host 0.0.0.0 --port 8000
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from apps.api.routes import chat as chat_routes
from apps.api.routes import system as system_routes

app = FastAPI(
    title="RAG Tutor API",
    version="0.1.0",
    description="API du tuteur pédagogique RAG (prototype vertical slice)",
)

# CORS large VOLONTAIREMENT pour le prototype en développement local
# (Next.js :3000 appelant FastAPI :8000 directement). Sera restreint au
# domaine réel en phase hardening.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)

app.include_router(system_routes.router, prefix="/api")
app.include_router(chat_routes.router, prefix="/api")
