# Implémentation du prototype vertical slice — Journal détaillé étape par étape

> Suite de l'audit (`audit-rag-tutor-v2.md`). Ce document trace, étape par étape,
> la construction du prototype web : **Next.js → FastAPI → `pipeline.answer()` →
> ChromaDB + Ollama → JSON → affichage**.
>
> Règle absolue respectée de bout en bout : **aucune modification de
> `src/rag_tutor/`** (le RAG existant est consommé tel quel).
>
> Date : 2026-09-15 · Branche : `main`

---

## Étape A — Inspection du code réel avant toute modification

Conformément à la consigne « ne suppose rien à partir de l'audit, lis le code »,
re-lecture ciblée de `core/pipeline.py`, `generator.py`, `retriever.py`,
`vector_store.py`, `llm_client.py` + vérification `git status`.

### Confirmations issues du code

1. **Signature exacte de `pipeline.answer()`** (`core/pipeline.py:52`) :

```python
def answer(query: str, k: int = 4, system_prompt: str | None = None,
           use_query_processing: bool = True, use_refusal_gate: bool = True,
           history: str | None = None, stream: bool = False) -> RAGResult:
```

2. **Structure exacte de `RAGResult`** (dataclass, `core/pipeline.py:33`) :

```python
@dataclass
class RAGResult:
    query: str
    rewritten_query: str
    sub_queries: list[str]
    hits: list[dict]        # dicts complets (text/dist/meta)
    contexts: list[str]     # textes seuls
    answer: str
    refused: bool           # True si M1 (reranker) ou M2 (juge LLM) a refusé
    answer_stream: Iterator[str] | None = None   # None en stream=False
```

3. **Structure exacte d'un hit** (`core/retriever.py`, `children_to_parents`) :

```python
{
  "text": "<section parente complète>",
  "dist": "<score : logit cross-encoder en hybrid_rerank>",
  "meta": {
    "source":      "chapter_..._transformer",     # nom de fichier sans extension
    "source_type": "web" | "pdf",
    "source_url":  "https://d2l.ai/..." | None,   # web uniquement
    "title":       "11.7. The Transformer Architecture" | None,  # web uniquement
    "source_id":   "02_NN.pdf" | None,            # pdf uniquement
    "page":        <int | None>,                  # = page_start
    "page_start":  <int | None>,
    "page_end":    <int | None>,
    "section":     "11.7.4. Encoder",
    "parent_id":   "chapter_..._transformer__sec012"
  }
}
```

Le libellé lisible existe déjà : `generator.citation_label(meta)` produit
`"web · d2l.ai · « 11.7. … » · §11.7.4. Encoder"` ou `"pdf · 02_NN.pdf · §1- …"`.
→ Réutilisé tel quel pour `sources[].label`. **Zéro invention d'URL/titre/section.**

4. **`history` est une chaîne pré-formatée** (`str | None`), PAS une liste.
   Format de référence = sortie de `ConversationMemory.get_formatted_history()` :

```text
[DERNIERS ÉCHANGES]
Étudiant : …
Tuteur : …
```

Elle est injectée telle quelle dans deux prompts : le query processing
(résolution des anaphores) et le générateur (contexte conversationnel).

5. **Exceptions réellement levables** :

| Origine | Exception | Mapping HTTP retenu |
|---|---|---|
| `vector_store.get_collection()` | `RuntimeError` (« Collection Chroma … introuvable ») | 503 `index_unavailable` |
| `vector_store.load_parents()` | `FileNotFoundError` (parents_*.json absent) | 503 `index_unavailable` |
| `llm_client.chat()` | `RuntimeError` (« Le modele Ollama '<m>' n'est pas disponible ») | 502 `model_unavailable` |
| embeddings / génération | erreurs client Ollama / réseau (`ollama.RequestError`, `httpx.HTTPError`) | 502 `ollama_unreachable` |
| `process_query`, `verify_answer`, `should_refuse_reranker` | **ne lèvent jamais** (fallbacks internes) | — |

Limite connue et assumée (non modifiée) : aucun timeout dans `llm_client.chat()`.
Traitement prévu en phase hardening.

### Décisions d'architecture prises à cette étape

- **Routes en `def` (pas `async def`)** : FastAPI exécute les handlers synchrones
  dans son threadpool (anyio) → le pipeline bloquant (appels Ollama, cross-encoder
  CPU, BM25) ne gèle jamais l'event loop ; `/health` reste servi pendant une
  génération de 30-90 s.
- **`history` du contrat API** : le frontend envoie
  `[{"role": "user"|"assistant", "content": "…"}]` (tours PRÉCÉDENTS uniquement,
  sans le message courant) ; le use case le sérialise au format pipeline
  (`user → Étudiant`, `assistant → Tuteur`). Le message courant n'est PAS dupliqué
  dans l'historique : dans le CLI il s'y trouve parce qu'il est ajouté AVANT
  l'appel ; côté API il est déjà passé comme `query`.
- **Pas de `settings.py` dans cette itération** : la config actuelle suffit
  (Ollama localhost, `chroma_db/` relatif au CWD → uvicorn lancé à la racine).
  Refactor config reporté pour ne pas mélanger les problèmes.

---

## Étape B — Backend FastAPI minimal

### B1. Dépendance (seule modification d'un fichier existant)

```bash
.venv/bin/pip install "fastapi>=0.115.0"     # fastapi 0.141.1 installé
```

`pyproject.toml` : ajout d'une ligne dans `dependencies` :

```toml
"fastapi>=0.115.0",
```

(pydantic 2.13.4 et uvicorn 0.52.4 étaient déjà présents dans `.venv`.)

### B2. Arborescence créée

```text
apps/
├── __init__.py
├── README.md                               # doc prototype (lancement, contrat, latence)
└── api/
    ├── __init__.py
    ├── main.py                              # FastAPI, CORS dev, préfixe /api
    ├── dependencies.py                      # provider use case + mapping exceptions
    ├── routes/
    │   ├── __init__.py
    │   ├── system.py                        # GET  /api/health
    │   └── chat.py                          # POST /api/chat
    ├── application/
    │   ├── __init__.py
    │   └── chat/
    │       ├── __init__.py
    │       └── chat_use_case.py             # SEULE couche qui connaît pipeline + schemas
    └── schemas/
        ├── __init__.py
        └── chat.py                          # ChatRequest, HistoryTurn, Source, ChatResponse
```

### B3. Rôle de chaque fichier

| Fichier | Responsabilité |
|---|---|
| `schemas/chat.py` | Contrat Pydantic. `message` 1–2000 chars, `k` 1–8 (défaut 4, cap assumé : chaque parent fait jusqu'à ~80K car.), `history` ≤ 40 tours. `Source` reflète EXACTEMENT `hits[*]["meta"]` (champs `None` autorisés car web et PDF ne portent pas les mêmes métadonnées). |
| `chat_use_case.py` | `format_history()` (sérialisation tours → format pipeline), `execute_chat()` : uuid4 si pas de `conversation_id`, mesure de latence, appel `pipeline_answer(message, k=k, history=..., stream=False)` (signature exacte), mapping `hits → sources` via `citation_label()`. |
| `dependencies.py` | `get_chat_use_case()` (DI) + `map_pipeline_exception()` : ordre de test = précision du message (index 503 → modèle 502 → réseau 502 → générique 500, détail interne non exposé). |
| `routes/chat.py` | Adaptateur HTTP minimal : `def chat(...)` → use case → mapping exceptions. Aucune logique RAG. |
| `routes/system.py` | `/api/health` : ping Ollama (`/api/tags`, timeout 2 s) + modèles requis, compte Chroma, existence du fichier parents, `MODE`/`RERANKER_ACTIVE` lus SANS déclencher `_lazy()` (aucun chargement de modèle). Retourne 200 même en `degraded` (sonde, pas erreur applicative). |
| `main.py` | App FastAPI, CORS limité à `localhost:3000`/`127.0.0.1:3000` (GET/POST), inclusion des routeurs sous `/api`. |

---

## Étape C — Tests backend réels (aucun mock)

Les processus de fond ne survivant pas entre les commandes du terminal distant,
chaque test a été exécuté en une commande : démarrage d'uvicorn → curl → arrêt.

### Test 1 — RAG CLI intact

`src/rag_tutor/` : 0 modification (vérifié au `git diff`). Les tests suivants
exercent le même chemin de code (`pipeline.answer()`) que le CLI.

### Test 2 — `GET /api/health` ✅

```json
{
  "status": "ok",
  "ollama": {"reachable": true, "models": ["qwen3:8b", "qwen2.5:14b", "…", "bge-m3:latest", "…"], "missing_models": []},
  "index": {"loaded": true, "children": 8952, "parents_file": true},
  "retrieval": {"mode": "hybrid_rerank", "reranker_active": true},
  "embedding_model": "bge-m3"
}
```

### Test 3 — `POST /api/chat`, vraie question ✅ (HTTP 200 en 36,3 s à froid)

Requête : `{"message":"Qu'est-ce qu'un LSTM en machine learning ?"}`

- `refused: false`, `latency_ms: 36324`
- Reformulation : « Qu'est-ce qu'un LSTM dans le contexte du machine learning et
  comment fonctionne-t-il? »
- 4 sources réelles, ex. :
  - `pdf · 05_RNN.pdf · §3.4- Machines de Turing neuronales` (score 0.82)
  - `pdf · 05_RNN.pdf · §3.1- LSTM` (score 0.78)
  - `web · d2l.ai · « 10.1. Long Short-Term Memory (LSTM) » · §10.1.3. Concise Implementation`
- Réponse ancrée avec citations obligatoires au format corpus
  (`… [pdf · 05_RNN.pdf · §3.1- LSTM] …`).

### Test 4 — Question hors corpus → refus ✅ (HTTP 200 en 56,6 s)

Requête : « Quelle est la capitale du Japon et comment cuisiner des ramen ? »
- `refused: true`, réponse = message verbatim
  « Les documents fournis ne permettent pas de répondre à cette question. »
- Déclenchement M1 (seuil reranker calibré 0.1119), aucun appel de génération
  inutile, 4 hits renvoyés pour transparence.

### Test 5 — Conversation multi-tours avec `history` ✅ (HTTP 200 en 27,5 s)

Requête : message « Et comment le compare-t-on au GRU ? » + historique
(user : question LSTM ; assistant : réponse LSTM), `conversation_id` repris
du tour 1 → **conservé tel quel dans la réponse**.

Preuve que l'anaphore est résolue par le query processing :
- reformulation = « Comment comparer un **LSTM** à un GRU en termes de
  fonctionnement et d'avantages/disavantages? » (« le » → « LSTM »)
- sources pertinentes : `web · d2l.ai · §10.2. Gated Recurrent Units (GRU)`.

### Test 6 — Frontend ✅

- `npm run build` : compilation + types strict OK (Next.js 15.5.25).
- `next start` : page HTTP 200, contenu « Tuteur Intelligent » présent.
- Preflight CORS (ce que fait le navigateur) :
  `access-control-allow-origin: http://localhost:3000`,
  `allow-methods: GET, POST`, `allow-headers: … Content-Type` ✅.

---

## Étape D — Frontend Next.js minimal (fonctionnement > esthétique)

Création manuelle du scaffold (contrôlé, sans les extras de create-next-app) :
Next.js 15 + React 19 + TypeScript strict + Tailwind CSS v4.

### Fichiers créés

| Fichier | Rôle |
|---|---|
| `package.json`, `tsconfig.json`, `next.config.ts`, `postcss.config.mjs`, `app/globals.css` | Socle Next 15 / Tailwind v4 (import CSS unique). |
| `lib/api.ts` | Client typé, contrat IDENTIQUE au backend (interfaces `Source`, `ChatResponse`), `ApiError` (code + status), gestion échec réseau et erreurs structurées `detail.code`/`detail.message`. `NEXT_PUBLIC_API_URL` configurable (défaut `http://localhost:8000`). |
| `app/layout.tsx` | Layout racine (lang fr, Tailwind). |
| `app/page.tsx` | Page de chat. État React pur : `messages[]`, `input`, `conversationId`, `loading`, `error`. Aucun state manager externe. |
| `components/ChatMessage.tsx` | Bulle user/tuteur ; bandeau ambre distinct si `refused` ; sources sous la réponse ; latence affichée. |
| `components/SourceList.tsx` | Liste des sources réelles : `label` (citation complète), lien UNIQUEMENT si `source_url` existe, pages pour les PDF. |
| `.gitignore` | `node_modules/`, `.next/`, `next-env.d.ts`, `*.tsbuildinfo`. |

### Conversation côté frontend (sans persistance serveur)

```text
user message
  ↓
history = messages[] filtrés (tours refusés exclus) → [{role, content}, …]
  ↓
POST /api/chat {message, conversation_id, history}
  ↓
réponse → messages[] + conversation_id mémorisé
```

- Au tour suivant, l'historique permet au backend de résoudre les anaphores
  (prouvé au Test 5).
- Refus : affiché comme information pédagogique (« le tuteur ne dispose pas
  d'informations suffisantes dans son corpus ») — aucune logique de refus
  dupliquée côté frontend, le refus vient du RAG.
- Erreurs : bandeau rouge avec code structuré (`ollama_unreachable`,
  `index_unavailable`, `network_error`…).

---

## Bilan

### Fichiers créés (16)

```text
apps/__init__.py
apps/README.md
apps/api/__init__.py
apps/api/main.py
apps/api/dependencies.py
apps/api/routes/__init__.py
apps/api/routes/system.py
apps/api/routes/chat.py
apps/api/application/__init__.py
apps/api/application/chat/__init__.py
apps/api/application/chat/chat_use_case.py
apps/api/schemas/__init__.py
apps/api/schemas/chat.py
apps/web/{package.json, tsconfig.json, next.config.ts, postcss.config.mjs, .gitignore}
apps/web/app/{layout.tsx, page.tsx, globals.css}
apps/web/components/{ChatMessage.tsx, SourceList.tsx}
apps/web/lib/api.ts
```

### Fichiers existants modifiés (1)

| Fichier | Changement |
|---|---|
| `pyproject.toml` | +1 ligne : `"fastapi>=0.115.0"` dans `dependencies` |

### Ce qui n'a PAS été touché (conforme aux règles)

- `src/rag_tutor/**` : **zéro modification** (pipeline, retrieval, prompts, refusal).
- `evaluation/` (Ragas/DeepEval) : intact, hors runtime.
- ChromaDB : tel quel (client embarqué, même index de 8 952 enfants).
- Ollama : non containerisé, même client.
- Pas de SSE, Docker, Nginx, PostgreSQL, Redis, auth, upload, persistance serveur.

### Latences observées (GPU H100 hôte, modèles Ollama locaux)

| Scénario | Durée |
|---|---|
| Première question (à froid : chargement reranker + 3 appels LLM) | 36 s |
| Question hors corpus (refus M1) | 57 s |
| Question de suivi (modèles chauds) | 27 s |

### Comment lancer

```bash
# Terminal 1 — backend (à la racine du projet : chroma_db/ est relatif au CWD)
.venv/bin/uvicorn apps.api.main:app --host 127.0.0.1 --port 8000

# Terminal 2 — frontend
cd apps/web && npm install && npm run dev     # → http://localhost:3000
```

### Prochaines étapes possibles (non implémentées, conformément à la consigne)

1. SSE `/api/chat/stream` — le streaming existe déjà dans le pipeline
   (`pipeline.answer(stream=True)` → `answer_stream`) ; émission d'événements
   `meta` (sources) puis `token` puis `done|error`.
2. Refactor configuration (`rag_tutor/settings.py` + `.env`).
3. Docker + Nginx + HTTPS.
