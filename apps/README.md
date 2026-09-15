# Tuteur RAG — API + Frontend (prototype)

Cette partie du projet ajoute la couche applicative web autour du RAG existant,
**sans modifier aucun composant de `src/rag_tutor/`**.

## Architecture du prototype

```text
Browser → Next.js (:3000) → POST /api/chat → FastAPI (:8000)
        → chat_use_case → rag_tutor.core.pipeline.answer()
        → ChromaDB + Ollama (RAG existant) → JSON → affichage
```

## Lancer le backend (FastAPI)

```bash
# À la racine du projet (important : chroma_db/ est résolu relativement au CWD)
.venv/bin/uvicorn apps.api.main:app --host 127.0.0.1 --port 8000

# Vérifications
curl http://localhost:8000/api/health
curl -X POST http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{"message":"Qu'"'"'est-ce qu'"'"'un LSTM ?"}'
```

Endpoints :
- `GET /api/health` — Ollama joignable, modèles présents, index Chroma chargé, mode de retrieval.
- `POST /api/chat` — question + historique optionnel → réponse, sources réelles, refus éventuel.

## Lancer le frontend (Next.js)

```bash
cd apps/web
npm install        # première fois uniquement
npm run dev        # http://localhost:3000
```

L'URL de l'API est configurable via `NEXT_PUBLIC_API_URL`
(défaut : `http://localhost:8000`).

## Contrat API (prototype JSON)

Request :
```json
{
  "message": "Et comment le compare-t-on au GRU ?",
  "conversation_id": "uuid-optionnel",
  "history": [{"role": "user", "content": "…"}, {"role": "assistant", "content": "…"}],
  "k": 4
}
```

Response :
```json
{
  "conversation_id": "…",
  "answer": "… [web · d2l.ai · « 10.2. GRU » · §10.2.6. Summary] …",
  "refused": false,
  "sources": [{"label": "web · d2l.ai · « … » · §…", "source_url": "https://…", "score": 6.4}],
  "meta": {"rewritten_query": "…", "sub_queries": [], "latency_ms": 27519}
}
```

- `history` : tours **précédents** uniquement (le message courant est déjà dans
  `message`). Le backend le formate pour la résolution des anaphores.
- `sources` : uniquement les métadonnées réelles des hits (`citation_label()`),
  jamais de champ inventé.
- `refused: true` : le corpus ne permet pas de répondre (mécanisme de refus M1/M2
  du RAG existant).

## Notes de latence

Le pipeline complet (reformulation LLM + retrieval hybride + reranker +
génération qwen2.5:14b + juge M2) prend **30 à 90 s** par question. Le premier
appel après démarrage est plus long (chargement du reranker en mémoire).
