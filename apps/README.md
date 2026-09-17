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
- `POST /api/chat/stream` — même contrat, en flux SSE (`meta` → `token`* → `done|error`).

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

## Contrat SSE (`POST /api/chat/stream`)

Même request body que `/api/chat`. Réponse `text/event-stream` :

```
event: meta     data: {"conversation_id":"…","refused":false,"sources":[…],"rewritten_query":"…","sub_queries":[]}
event: token    data: {"delta":"La backprop"}
event: token    data: {"delta":"agation …"}
event: done     data: {"latency_ms":8400}
```

- `meta` est émis dès la fin du retrieval (avant le premier token) : les sources
  s'affichent immédiatement. Les sources utilisent exactement le même schéma que
  le mode JSON.
- Consommation frontend : `sendChatStream()` dans `apps/web/lib/api.ts`
  (fetch + ReadableStream, parsing incrémental des blocs `\n\n`), affichage des
  tokens au fur et à mesure dans `app/page.tsx`, curseur de streaming dans
  `components/ChatMessage.tsx`. En cas d'erreur en cours de flux, les tokens
  déjà affichés sont conservés.
- Refus M1 (seuil reranker) : `meta` porte `refused:true`, suivi de `done` —
  aucun `token` (testé).
- Erreur pendant la génération (en-têtes déjà envoyés) : `event: error`
  `data: {"code":"…","message":"…","status":502}` puis fermeture. Une erreur
  survenue AVANT le premier token (retrieval, index, validation) reste une
  erreur HTTP 5xx/422 classique, le flux n'est jamais ouvert.
- Le M2 (juge post-génération) est inactif en streaming — contrainte du RAG
  existant (il nécessite la réponse complète), déjà documentée dans le code.

Exemple :
```bash
curl -sN -X POST http://localhost:8000/api/chat/stream \
  -H "Content-Type: application/json" \
  -d '{"message":"Qu'"'"'est-ce qu'"'"'un LSTM ?"}'
```

## Notes de latence

Le pipeline complet (reformulation LLM + retrieval hybride + reranker +
génération qwen2.5:14b + juge M2) prend **30 à 90 s** par question. Le premier
appel après démarrage est plus long (chargement du reranker en mémoire).

En SSE, la phase bloquante (reformulation + retrieval + refus M1, 15–30 s)
précède l'ouverture du flux : après les en-têtes, le premier token arrive
généralement en 1–3 s (génération qwen2.5:14b, modèles chauds).

IMPORTANT — un seul worker Uvicorn : ChromaDB est un client embarqué sur un
chemin partagé (`chroma_db/`), ne pas lancer avec `--workers N`.
