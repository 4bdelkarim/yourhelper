# Audit rag-tutor-v2 — PHASE 1 (aucun fichier modifié)

> Audit technique réalisé le 2026-09-15 par exploration réelle du repository :
> structure, `src/rag_tutor/` complet (core, conversation, cli, ingestion, extraction, evaluation),
> `Makefile`, `pyproject.toml`, `config/`, `.env.example`, `.gitignore`, `chroma_db/` (inspecté),
> `data/`, `eval/`, environnement machine (Ollama, Docker, GPU) vérifié en direct.

---

# 1. Executive Summary

Le projet `rag-tutor-v2` est un système RAG **100 % local** mature et bien architecturé côté Python : pipeline de requête propre (`core/pipeline.py`), retrieval hybride BM25 + dense + RRF + cross-encoder avec remontée parents, double refus M1/M2, streaming token-par-token déjà fonctionnel, mémoire conversationnelle avec compression. Le code est **réutilisable quasi tel quel** — le README est fidèle au code réel (vérifié fichier par fichier).

**Ce qui manque entièrement** : toute couche applicative web. Aucune API, aucun frontend, aucun Docker, aucun test unitaire, aucune config externalisée (tout est en constantes hardcodées dans `core/`).

**Verdict** : le RAG ne doit **pas** être réécrit ni déplacé massivement. Le travail MVP consiste à construire `apps/api` (FastAPI) et `apps/web` (Next.js) **autour** du package existant, avec un léger refactor de configuration. L'environnement machine est excellent (H100, 208 cœurs, 755 Go RAM, Docker 29), Ollama tourne déjà avec tous les modèles requis et l'index ChromaDB est peuplé (8 952 embeddings, 1 953 parents).

Risque principal : le pipeline est **synchrone et bloquant** (Ollama, cross-encoder) — l'API devra l'exécuter hors de l'event loop. Effort total estimé : **6 à 9 jours** pour un MVP déployable.

---

# 2. Architecture actuelle

## Organisation réelle du dépôt

```text
rag-tutor-v2/
├── Makefile                  # setup / ingest / chat / tutor / eval / clean
├── pyproject.toml            # package "rag-tutor" v2.1.0, src-layout, 3 entry points CLI
├── config/config.yaml        # config GLM-OCR uniquement (extraction PDF) — PAS le runtime
├── .env.example              # documente les constantes — AUCUNE variable lue au runtime
├── chroma_db/                # index ChromaDB PERSISTANT (37 Mo sqlite + parents_cours_ml_fig.json)
├── data/                     # raw/ → processed/ → normalized/ (243 .md canoniques)
├── eval/                     # datasets d'évaluation (golden_dataset_v2.json, calibration…)
├── scripts/fetch_reranker.py # pré-téléchargement bge-reranker-v2-m3
└── src/rag_tutor/            # LE package Python
    ├── core/                 # ★ pipeline, query_processing, retriever, refusal_gate,
    │                         #   generator, llm_client, embeddings, vector_store, chunking
    ├── conversation/         # memory.py (compression résumé cumulatif), prompts.py (socratique)
    ├── cli/                  # chat.py (Q&A direct), tutor.py (socratique + streaming)
    ├── ingestion/            # ingest.py (chunking → embeddings → Chroma)
    ├── extraction/           # pdf_extractor (GLM-OCR), web_scraper, web_crawler, normalizer
    └── evaluation/           # evaluate, calibrate, dataset_gen, per_question, validate_judge
```

## Chemin d'une requête utilisateur (actuellement CLI uniquement)

```text
User (terminal)
 ↓
cli/chat.py ou cli/tutor.py
 ↓
core/pipeline.answer(query, k, system_prompt, history, stream)
 ↓
core/query_processing.process_query()      — 1 appel LLM (reformulation + décomposition JSON,
 │                                            résolution d'anaphores via history)
 ↓ (round-robin si sous-questions, dedup parent_id)
core/retriever.retrieve(question, k)       — MODE = "hybrid_rerank" :
 │    _dense()      → Chroma query, bge-m3 via Ollama /api/embed, cosinus
 │    _bm25_search()→ rank-bm25 sur les ENFANTS (corpus entier chargé en RAM au 1er appel)
 │    _rrf_fusion() → RRF pondéré (α=0.6 dense, k=60)
 │    _rerank()     → CrossEncoder bge-reranker-v2-m3 (CPU, sentence-transformers)
 │    children_to_parents() → remontée sections complètes, dedup
 ↓
refusal_gate.should_refuse_reranker(hits)  — M1 : max(score) < 0.1119 → REFUSAL_MESSAGE
 ↓ (si stream : bypass M2, yield generate_stream)
core/generator.generate()                  — prompt ancrage strict + citations obligatoires,
 ↓                                            qwen2.5:14b via Ollama, max_tokens 900, num_ctx 24576
generator.verify_answer()                  — M2 : juge qwen3:8b, verdict ANCRÉ/HORS-CONTEXTE
 ↓
RAGResult{query, rewritten_query, sub_queries, hits[{text,dist,meta}], contexts, answer, refused, answer_stream}
```

## Points d'usage des infrastructures

- **ChromaDB** : `vector_store.py` est le **seul** module qui connaît `DB_DIR="chroma_db"`, `COLLECTION_NAME="cours_ml_fig"`, l'espace cosinus et le format `parents_*.json`. Client embarqué (`PersistentClient`), pas de serveur Chroma. Index réel vérifié : 8 952 embeddings enfants, 1 953 parents avec metadata riche (`source_type`, `source_url`, `title`, `section`, `page_start/end`).
- **Ollama** : client explicite `ollama.Client(host="http://127.0.0.1:11434")` dans `llm_client.py` **et** `embeddings.py` (jamais la variable d'env — choix volontaire documenté). Modèles : `qwen2.5:14b` (génération), `qwen3:8b` (juge M2 + compression mémoire), `bge-m3` (embeddings). `keep_alive="30m"` réutilise le modèle entre requêtes.
- **Reranker** : hors Ollama (Ollama n'expose pas la tête cross-encoder), via sentence-transformers sur CPU, cache HF présent sur la machine. Dégradation automatique vers `hybrid` si indisponible (`RERANKER_ACTIVE=False`, et M1 se désactive alors tout seul).
- **Configuration** : constantes en tête de chaque module core (`GEN_MODEL`, `MODE`, `RERANKER_REFUSAL_THRESHOLD=0.1119`, `OLLAMA_HOST`, `MAX_TOKENS=900`…). `config/config.yaml` ne concerne que GLM-OCR. Rien n'est lu depuis l'environnement.

## Composants directement réutilisables dans le MVP

- `pipeline.answer()` — **le point d'entrée unique**, déjà conçu pour « toute interface interactive (CLI/Streamlit) ». Signature stable, retour dataclass `RAGResult`.
- `pipeline.answer(stream=True)` + `generate_stream`/`chat_stream` — le streaming existe déjà, il suffit de le brancher.
- `retriever`, `refusal_gate`, `generator`, `query_processing`, `llm_client`, `embeddings`, `vector_store` — intacts.
- `generator.citation_label(meta)` — produit déjà des libellés de citation lisibles pour l'affichage des sources.
- `conversation.memory.ConversationMemory` — utilisable serveur si besoin plus tard ; pour le MVP l'historique sera passé via le paramètre `history` (déjà supporté par `answer()`).

## État de chaque composant

| Composant        | État actuel | Réutilisable ? | Modifications nécessaires |
| ---------------- | ----------- | -------------- | ------------------------- |
| RAG pipeline     | Fait, sain (`core/pipeline.py`, 185 l.) — orchestre QP→retrieval→refus→génération | ✅ tel quel | Aucune (point d'entrée unique) |
| ChromaDB         | Index peuplé (8 952 enfants / 1 953 parents), client embarqué | ✅ tel quel | Chemin configurable (settings) |
| Dense retrieval  | Fait (bge-m3 via Ollama `/api/embed`, cosinus) | ✅ tel quel | Aucune |
| BM25             | Fait (rank-bm25, corpus en RAM, `_lazy()`) | ✅ tel quel | Aucune (connaissance : GIL-bound) |
| RRF              | Fait (pondérée α=0.6, k=60) | ✅ tel quel | Aucune |
| Reranker         | Fait (CrossEncoder CPU, fallback dégradé géré) | ✅ tel quel | Aucune |
| Refusal gate     | Fait (M1 seuil calibré 0.1119 + M2 juge qwen3:8b) | ✅ tel quel | Aucune |
| Query processing | Fait (reformulation + décomposition, repli sûr) | ✅ tel quel | Aucune |
| LLM              | Fait (`llm_client.chat`/`chat_stream`, client explicite) | ✅ tel quel | Host + timeouts configurables |
| Conversation     | Fait (`ConversationMemory` + prompts socratiques) | ✅ tel quel | Aucune (history déjà paramètre d'`answer()`) |
| API              | **Inexistante** | — | **NEW intégral** (FastAPI) |
| Frontend         | **Inexistant** | — | **NEW intégral** (Next.js) |
| Docker           | **Inexistant** | — | **NEW intégral** (Dockerfiles + compose) |
| Tests            | **Inexistants** (uniquement `evaluation/`, hors runtime) | — | **NEW** (pytest unitaires + API) |
| Évaluation       | Fait, riche (Ragas/DeepEval/calibration) | Hors MVP | Découplée de `cli/tutor.py` |

---

# 3. Analyse détaillée du RAG

| Élément | Observation vérifiée |
|---|---|
| **Query processing** | 1 appel LLM, sortie JSON parseée avec repli silencieux sur la question brute. Jamais d'exception. La question reformulée est toujours retenue + sous-questions ajoutées (fix documenté Run 2). |
| **Dense retrieval** | Chroma `query()`, similarité `1 - dist` cosinus. Embeddings déjà normalisés côté Ollama. |
| **BM25** | `BM25Okapi` sur 8 952 enfants, tokenisation `.lower().split()` (pas de stemming FR — acceptable, c'est le comportement évalué). Corpus chargé **une fois** en RAM (`_lazy()`). |
| **RRF** | Fusion pondérée α=0.6, k=60, avec copie défensive des candidats. Bien implémentée. |
| **Reranker** | CrossEncoder CPU, 3 tentatives avec purge de cache corrompu, flag public `RERANKER_ACTIVE`. Les scores reranker remplacent les scores RRF (`hits["dist"]`). |
| **Parents** | Remontée + dedup `parent_id`, metadata complète propagée (source, url, titre, section, pages). C'est ce qui rendra l'affichage des sources trivial côté web. |
| **Refusal M1** | Seuil 0.1119 calibré (`eval/reranker_calibration.json`), max sur tous les hits (fix récent), auto-désactivation si reranker absent. |
| **Refusal M2** | Juge qwen3:8b, parsing robuste multi-fallbacks, échec technique = conservateur (ne bloque pas). Fallback sur GEN_MODEL si juge absent. |
| **Génération** | Prompt d'ancrage strict avec refus verbatim + citations obligatoires `[web · d2l.ai · « … » · §…]`. Deux prompts : professeur direct (`DEFAULT_SYSTEM_PROMPT`) et socratique (`TUTOR_SYSTEM_PROMPT`). |
| **Streaming** | `answer(stream=True)` retourne `answer_stream` (itérateur de tokens). **M2 est contourné en streaming** (nécessite la réponse complète) — compromis assumé et documenté. |
| **Mémoire conversationnelle** | `ConversationMemory` : fenêtre 6 tours + résumé cumulatif LLM, élagage, bornée à 12 tours. `history` est injectée à la fois dans le query processing (anaphores) et la génération. |

**Conclusion : le pipeline est sain, testé par l'évaluation, et son orchestrateur est déjà « prêt pour une interface ».**

---

# 4. Analyse de la structure du repository

### Problèmes de couplage
1. **`cli/tutor.py` importe `evaluation/per_question.py`** → l'évaluation (Ragas/DeepEval) est dans le graphe d'imports du runtime conversationnel. Contre la règle « évaluation hors MVP ». À découpler (optionnel : garder `--show-eval` en CLI seulement).
2. **Configuration par constantes module** : `retriever.MODE`, `OLLAMA_HOST`, etc. sont lus comme attributs de module au moment de l'appel → impossibles à surcharger proprement par l'API sans toucher aux globals.
3. **`retriever` : singletons globaux lazy** (`_EMBEDDER`, `_COLL`, `_BM25`…) — acceptable pour un process API mono-instance, mais incompatible avec un rechargement de collection à chaud et gênant pour les tests.

### Problèmes d'organisation
4. `format_sources()` **dupliqué** à l'identique dans `cli/chat.py` et `cli/tutor.py`.
5. Aucune séparation « lib / app » : le package `rag_tutor` est propre, mais il n'y a **aucune** couche applicative (ni API, ni schemas, ni DI).
6. `.deepeval/` présent à la racine (artefact d'évaluation) — hors runtime mais salit le dépôt.

### Problèmes de production
7. **Zéro timeout réseau** sur les appels Ollama (génération peut durer des minutes) → une requête API peut pendre indéfiniment.
8. `print()` partout au lieu de `logging` (y compris dans le chemin de requête : dégradation reranker, retries embeddings).
9. **`chroma_db/` versionné dans git** et modifié à chaque accès (38 Mo de binaire, `git status` le montre modifié) — artefact runtime dans le VCS.
10. Aucun test automatisé (seulement `evaluation/` qui est de l'eval de qualité, pas des tests logiciels).
11. Concurrence : `rank_bm25.get_scores()` et le CrossEncoder sont GIL-bound et séquentiels — deux requêtes simultanées se serialisent (acceptable MVP, à connaître). Chroma `PersistentClient` n'est pas conçu pour plusieurs process sur le même chemin → **un seul worker Uvicorn** sur ce chemin de DB.

### API / Frontend
12. **Aucune API. Aucun frontend. Aucun Docker. Aucun Nginx.** Rien à analyser — c'est du NEW intégral.

---

# 5. KEEP / REFACTOR / REWRITE / REMOVE / NEW

| Décision | Éléments | Justification |
|---|---|---|
| **KEEP** (quasi tel quel) | `core/*` en entier (pipeline, retriever, refusal_gate, generator, llm_client, embeddings, vector_store, chunking, query_processing), `conversation/*`, `ingestion/`, `extraction/`, `scripts/fetch_reranker.py`, `Makefile`, `eval/`, `evaluation/` | Code sain, évalué, commentaires de traçabilité précieux. Le principe « on cherche petit, on génère grand » et les fallbacks sont le fruit d'itérations mesurées. |
| **REFACTOR** (léger) | Constantes de config (`llm_client`, `embeddings`, `retriever`, `refusal_gate`, `vector_store`) → module `rag_tutor/settings.py` lu depuis l'env (avec valeurs actuelles par défaut) ; imports d'`evaluation` retirés de `cli/tutor.py` ; unifier `format_sources` dans `core/generator.py` ; `print()` → `logging` sur le chemin requête ; `.gitignore` : `chroma_db/`, `.deepeval/` + `git rm --cached` | Nécessaire pour déployer derrière FastAPI/Docker (hosts configurables) sans toucher à la logique. Le comportement par défaut reste identique. |
| **REWRITE** | **Rien** | Aucun composant n'empêche une bonne architecture. `pipeline.answer()` est déjà le point d'entrée unique voulu. |
| **REMOVE** | Rien du code. En revanche : **déversionner** `chroma_db/` (artefact binaire modifié au runtime) ; `.deepeval/` hors git | Hygiène repo, pas de suppression de fichiers. |
| **NEW** | `apps/api/` (FastAPI : routes, schemas, use cases, deps), `apps/web/` (Next.js+TS+Tailwind : chat UI), `infra/` (Dockerfiles, nginx.conf), `docker-compose.yml`, `tests/` | Couche applicative inexistante. |

> **Adaptation de l'arborescence cible proposée dans le brief initial** : conserver **`src/rag_tutor/`** (src-layout PEP 621 standard, déjà installé en editable) plutôt que de le déplacer vers `packages/rag_tutor/` — le déplacement n'apporte aucun bénéfice fonctionnel et casse l'egg-link/entry points pour du churn pur. Les apps vivent dans `apps/` comme prévu.

---

# 6. Architecture MVP recommandée

```text
                    INTERNET
                       │ HTTPS (certbot, phase déploiement)
                     NGINX  :80/:443
                   ┌─────┴─────┐
                 / (UI)     /api/
                   │           │
              Next.js:3000  FastAPI:8000
                              │
                 POST /api/chat (JSON puis SSE /api/chat/stream)
                              │
                     chat_use_case
                              │
                rag_tutor.core.pipeline.answer()
                              │
        ┌─────────────────────┼──────────────────────┐
   query_processing       retrieval             generation
   (qwen2.5:14b)     BM25+dense+RRF+rerank    (qwen2.5:14b)
                         │         │
                    chroma_db/   bge-reranker
                  (volume local,  (CPU, cache HF)
                   client embarqué)        │
                                    M2 judge qwen3:8b
                              │
                    Ollama HOST (127.0.0.1:11434, non containerisé)
```

Décisions structurantes :
- **`rag_tutor` reste une lib** importée par `apps/api` — l'API ne connaît ni Chroma, ni le reranker, ni les prompts. Elle appelle `pipeline.answer()` et mappe `RAGResult` → JSON.
- **Routes = adaptateurs** : `routes/chat.py` → `application/chat/chat_use_case.py` → `rag_tutor.core.pipeline`. Exécution sync dans le threadpool FastAPI (endpoints `def`, pas `async def`) car le pipeline est bloquant.
- **Conversations MVP : côté client** (React state). Le `conversation_id` est généré par le frontend et simplement retourné par l'API. L'historique est envoyé en clair (liste de tours) — `pipeline.answer(history=…)` le supporte déjà, y compris pour la résolution d'anaphores.
- **Un worker Uvicorn** (Chroma embarqué + singletons RAM BM25/reranker).

---

# 7. Arborescence cible

```text
rag-tutor-v2/
├── src/rag_tutor/                  # KEEP — inchangé (cf. §5), sauf :
│   ├── settings.py                 # NEW-refactor : config env (OLLAMA_HOST, DB_DIR, MODE, seuils…)
│   └── core/…                      # constantes remplacées par lecture de settings (défauts = valeurs actuelles)
├── apps/
│   ├── api/
│   │   ├── main.py                 # FastAPI, CORS, exception handlers, /health
│   │   ├── routes/
│   │   │   ├── chat.py             # POST /api/chat, POST /api/chat/stream
│   │   │   └── system.py           # GET /api/health
│   │   ├── application/
│   │   │   └── chat/chat_use_case.py   # appelle pipeline.answer(), mappe RAGResult
│   │   ├── schemas/
│   │   │   └── chat.py             # ChatRequest, Source, ChatResponse, ChatEvent (SSE)
│   │   ├── dependencies.py         # settings, pipeline provider
│   │   └── Dockerfile
│   └── web/
│       ├── app/                    # App Router Next.js
│       │   ├── page.tsx            # chat UI
│       │   └── layout.tsx
│       ├── components/             # ChatMessage, MessageList, ChatInput, SourceCard, RefusalBadge
│       ├── lib/api.ts              # client fetch typé (JSON puis SSE)
│       └── Dockerfile
├── infra/
│   └── nginx/nginx.conf            # / → web, /api/ → api ; config SSE
├── tests/
│   ├── test_refusal_gate.py        # unitaires pur Python, sans LLM
│   ├── test_retriever_fusion.py    # RRF, parents dedup (fixtures, sans Chroma)
│   └── test_api_chat.py            # FastAPI TestClient + monkeypatch pipeline
├── docker-compose.yml
├── Makefile                        # + cibles api / web / docker-up
├── pyproject.toml                  # + deps fastapi[standard]
├── README.md                       # + section MVP web
├── .gitignore                      # + chroma_db/, .deepeval/, node_modules/, .next/
└── chroma_db/                      # déversionné, reste sur disque (volume Docker en phase 8)
```

---

# 8. Contrat API

Endpoints MVP — **volontairement minimal** : pas de `POST /conversations` ni `GET /conversations/{id}` car aucune persistance serveur au MVP (endpoints inutiles aujourd'hui ; ils seront naturels en phase 2 du produit avec un vrai store).

### `GET /api/health`

| | |
|---|---|
| **Rôle** | Sonde de vie + diagnostic des dépendances (compose healthcheck, debug déploiement). |
| **Response 200** | ```json
{"status":"ok","ollama":{"reachable":true,"models":["qwen2.5:14b","qwen3:8b","bge-m3"]},"index":{"loaded":true,"children":8952,"parents":1953},"reranker_active":true,"mode":"hybrid_rerank"}``` |
| **Erreurs** | `200` avec `"status":"degraded"` si Ollama injoignable ou index absent (jamais de 5xx sur /health, sinon les healthchecks killent le container). |

### `POST /api/chat`

| | |
|---|---|
| **Rôle** | Poser une question au tuteur ; le backend exécute le pipeline complet. |
| **Request** | ```json
{"message":"Explique-moi les réseaux de neurones","conversation_id":"b7e2…","history":[{"role":"user","content":"…"},{"role":"assistant","content":"…"}],"k":4}```
`conversation_id` et `history` optionnels (premier tour : absents). `k` optionnel (défaut 4, cap 8). Validation Pydantic : `message` 1–2000 chars. |
| **Response 200** | ```json
{"conversation_id":"b7e2…","answer":"…[web · d2l.ai · « 4.1. … » · §4.1. …]…","refused":false,"sources":[{"label":"web · d2l.ai · « 4.1. » · §4.1.","source_type":"web","source_url":"https://d2l.ai/…","title":"…","section":"4.1. …","page_start":null,"page_end":null,"score":6.42}],"meta":{"rewritten_query":"…","sub_queries":[],"latency_ms":8400}}``` |
| **Erreurs** | `422` validation ; `503` `{"detail":{"code":"index_unavailable",…}}` si Chroma/parents absents ; `502` `{"detail":{"code":"ollama_unreachable"}}` ; `504` si timeout génération. |
| **Sources** | Construites **uniquement** depuis `hits[*].meta` réels (source_type, source_url, title, section, page_start/end, score) — via `citation_label()`. Aucune donnée fictive. |

### `POST /api/chat/stream` *(phase SSE — même request body)*

Events `text/event-stream` :

```
event: meta     data: {"conversation_id":"…","sources":[…],"refused":false,"rewritten_query":"…"}
event: token    data: {"delta":"La backprop"}
event: token    data: {"delta":"agation …"}
event: done     data: {"latency_ms":8400}
event: error    data: {"code":"ollama_unreachable","message":"…"}
```

Le `meta` est émis dès que le retrieval est terminé (avant le premier token) → le frontend affiche les sources immédiatement, puis le texte s'écrit en streaming. En cas de refus M1, `meta` contient `refused:true` et `done` suit sans tokens.

---

# 9. Roadmap complète

```text
PHASE 0 — Audit (fait, ce document)
PHASE 1 — Hygiène & fondations : settings.py env-driven, logging, .gitignore/chroma_db,
          découplage evaluation↔tutor, deps fastapi, tests unitaires de base
PHASE 2 — apps/api : FastAPI /health + /chat JSON (sync/threadpool), schemas Pydantic,
          gestion d'erreurs structurée, test API
PHASE 3 — apps/web : init Next.js+TS+Tailwind, UI chat multi-tours, sources
PHASE 4 — Intégration front↔back : lib/api.ts, gestion erreurs/refus, conversation côté React
PHASE 5 — SSE /api/chat/stream + consommation front
PHASE 6 — Docker : Dockerfiles api/web, docker-compose, volume chroma_db, Ollama hôte
PHASE 7 — Nginx : / → web, /api/ → api, config SSE, (HTTPS cible déploiement)
PHASE 8 — Hardening : timeouts, limites, CORS, healthchecks compose, logs
PHASE 9 — Documentation : README MVP, .env.example réel, runbook
```

---

# 10. Plan d'implémentation étape par étape

### Étape 1 — `rag_tutor/settings.py` + bascule des constantes

- **Objectif** : configurer sans toucher au code (hosts, chemins, seuils, MODE).
- **Fichiers** : créer `src/rag_tutor/settings.py` ; modifier en tête de `core/llm_client.py`, `core/embeddings.py`, `core/retriever.py`, `core/refusal_gate.py`, `core/vector_store.py` pour lire les settings (défauts = valeurs actuelles exactes).
- **Actions** : dataclass/pydantic-settings ; `OLLAMA_HOST`, `GEN_MODEL`, `JUDGE_MODEL`, `EMBEDDING_MODEL`, `RERANKER_MODEL`, `DB_DIR`, `COLLECTION_NAME`, `RETRIEVAL_MODE`, `RERANKER_REFUSAL_THRESHOLD`, `MAX_TOKENS`, `NUM_CTX`, timeouts.
- **Dépendances** : aucune. **Résultat** : comportement identique sans env, configurable avec.
- **Test** : `make chat K=4` répond encore + `pytest tests/test_settings.py`.
- **Risques** : altérer une valeur par défaut → tests de régression + diff de comportement CLI. **Rollback** : `git revert` du commit.

### Étape 2 — Hygiène repo & découplage évaluation

- **Actions** : `.gitignore += chroma_db/, .deepeval/` ; `git rm --cached chroma_db/chroma.sqlite3` ; retirer l'import `evaluation.per_question` de `cli/tutor.py` (import paresseux derrière `--show-eval`) ; logging à la place des `print()` du chemin requête ; ajouter `fastapi[standard]` à `pyproject.toml`.
- **Test** : `git status` propre pendant le chat ; `make tutor` sans régression. **Rollback** : revert.

### Étape 3 — Squelette `apps/api` + `/health`

- **Actions** : `apps/api/main.py` (FastAPI, CORS dev), `routes/system.py`, `dependencies.py` (settings, lazy pipeline provider), schemas de base. `/health` vérifie Ollama (`GET /api/tags`, timeout 2 s), la présence de l'index (`get_collection` + count), et expose `reranker_active`/`mode`.
- **Test** : `uvicorn apps.api.main:app --reload` ; `curl /api/health`.
- **Risques** : import de `rag_tutor` depuis `apps/` → gérer via package installé (editable déjà en place). **Rollback** : supprimer `apps/api`.

### Étape 4 — `POST /api/chat` JSON

- **Fichiers** : `application/chat/chat_use_case.py`, `routes/chat.py`, `schemas/chat.py`.
- **Actions** : endpoint `def` (threadpool) ; construit la chaîne `history` depuis les tours passés ; `pipeline.answer(message, k, history=…)` ; mappe `RAGResult` → `ChatResponse` (sources depuis `hits[*].meta` + `citation_label`) ; handlers d'erreurs structurés (503 index, 502 Ollama, 422 validation) ; timeout global (ex. 120 s → 504).
- **Test** : `pytest tests/test_api_chat.py` (pipeline mocké) + curl réel avec Ollama.
- **Risques** : latence longue (30–60 s : reformulation + retrieval + génération + juge) → timeout Frontend/Proxy à caler ; concurrence (serialisation GIL). **Rollback** : revert.

### Étape 5 — Init Next.js + UI chat

- **Actions** : `apps/web` (Next 15, TS, Tailwind), composants `ChatMessage`/`MessageList`/`ChatInput`/`SourceCard`/`RefusalBadge`, état conversation dans `useState` (tours + conversation_id UUID), `lib/api.ts` typé, rendu des sources sous chaque réponse, bandeau pour refus, gestion erreurs (toast + message inline), indicateur de chargement.
- **Test** : `npm run dev` + question réelle via `/api/chat`. **Risques** : CORS en dev (proxy Next ou `NEXT_PUBLIC_API_URL`). **Rollback** : supprimer `apps/web`.

### Étape 6 — SSE

- **Actions** : `POST /api/chat/stream` — même use case, `pipeline.answer(stream=True)`, émission `event: meta` (sources, refused, rewritten) puis `StreamingResponse(media_type="text/event-stream")` en itérant `answer_stream` via `iterate_in_threadpool` ; ping keepalive ; `done`/`error` finaux ; front : parse du flux (`fetch` + `ReadableStream`), affichage incrémental, fallback JSON si SSE échoue.
- **Test** : curl `-N` sur /api/chat/stream ; UI en streaming. **Risques** : buffering proxy (off en phase Nginx) ; M2 inactif en streaming (déjà le cas dans le code — note doc seulement). **Rollback** : le front retombe sur /chat JSON.

### Étape 7 — Docker

- **Actions** : `apps/api/Dockerfile` (venv + deps torch/CPU, volume `chroma_db` read-only, `OLLAMA_HOST=host.docker.internal`, `extra_hosts`), `apps/web/Dockerfile` multi-stage (node build → runner), `docker-compose.yml` (services `api`, `web`, healthchecks ; **pas** d'Ollama ni Chroma-server).
- **Décision explicite** : **Ollama reste sur l'hôte** (modèles déjà pullés, GPU H100 disponible, conteneuriser = reproduire GPU passthrough + 30 Go de modèles pour rien). **ChromaDB reste embarqué** dans l'API (PersistentClient + volume bind `./chroma_db:/app/chroma_db`) — pas de serveur Chroma au MVP. Un seul worker Uvicorn.
- **Test** : `docker compose up --build` ; chat fonctionnel via compose. **Risques** : réseau hôte (host.docker.internal sous Linux → `extra_hosts: host-gateway`) ; poids image torch. **Rollback** : `docker compose down`, run natif conservé.

### Étape 8 — Nginx

- **Actions** : `infra/nginx/nginx.conf` : `location /` → `web:3000` ; `location /api/` → `api:8000` ; pour SSE : `proxy_buffering off`, `proxy_read_timeout 300s`, `proxy_http_version 1.1` ; limites `client_max_body_size 1m` ; HTTPS terminé plus tard (certbot) — config prépare les blocs 443.
- **Test** : curl via nginx ; SSE non bufferisé. **Rollback** : contourner nginx en dev.

### Étape 9 — Hardening + docs

- **Actions** : timeouts Ollama (via options client ou timeout HTTP), cap `k`, validation Pydantic stricte, logs JSON simples + request id, CORS restreint au domaine, `.env.example` réel (maintenant lu !), README section MVP (architecture, run, endpoints), checklist déploiement HTTPS.
- **Test** : revue des headers, healthchecks compose green. **Rollback** : n/a (config).

---

# 11. Stratégie SSE

- **Ce qui devient générateur** : c'est **déjà fait** — `pipeline.answer(stream=True)` retourne `RAGResult.answer_stream` (itérateur de str) via `generate_stream` → `chat_stream` (`ollama.Client.chat(stream=True)`). Le retrieval et le query processing restent synchrones : on collecte d'abord le contexte, on émet `meta` (sources/refus), puis on stream la génération. **Aucune modification du RAG n'est requise.**
- **Ollama** : inchangé — le client Python gère le SSE d'Ollama nativement ; `keep_alive="30m"` évite les cold starts entre tokens/requêtes.
- **FastAPI** : `StreamingResponse(generator, media_type="text/event-stream")`. Le générateur sync est consommé avec `anyio.to_thread.iterate_in_threadpool` (ou itération dans un `run_in_executor`), pour ne jamais bloquer l'event loop. Events `meta` → `token`* → `done`|`error`. Le M1 (refus pré-génération) fonctionne en streaming ; M2 est contourné (contrainte intrinsèque, déjà documentée dans le code).
- **Next.js** : `fetch` POST + lecture du body `ReadableStream`, décodage ligne par ligne (`event:`/`data:`), état React incrémental ; sources rendues dès `meta`. Pas besoin d'EventSource (il ne fait pas de POST).
- **Erreurs en streaming** : si l'erreur survient avant le 1er token → HTTP 5xx classique. Si elle survient pendant le flux (headers déjà envoyés) → `event: error` puis fermeture propre ; le frontend garde les tokens déjà affichés et montre l'erreur. Timeout client désactivé côté stream + `proxy_read_timeout 300`.
- **Client disconnect** : FastAPI lève une exception d'itération → le générateur est fermé (`finally` → `chat_stream` termine, Ollama annule à la fermeture du stream côté client).

---

# 12. Stratégie Docker

**Conteneurs : 3 seulement.** `api` (FastAPI+Uvicorn, 1 worker), `web` (Next.js standalone), `nginx`.

**Ollama : PAS containerisé.** Justification terrain : Ollama tourne déjà sur l'hôte avec les 4 modèles requis (dont qwen2.5:14b ~9 Go et bge-m3), GPU H100 visible, client explicite → il suffit de le paramétrer. Conteneuriser = NVIDIA Container Toolkit + re-téléchargement des modèles ou volume système + rien à gagner. L'API le contacte via `OLLAMA_HOST=http://host.docker.internal:11434` (`extra_hosts: ["host.docker.internal:host-gateway"]` sous Linux).

**ChromaDB : PAS un service.** Chroma est utilisé en **client embarqué** (`PersistentClient`) — le mode serveur n'existe pas dans le code actuel. Le dossier `chroma_db/` (index existant de 8 952 vecteurs) est bind-mounté en lecture dans le container API. Réindexation = `make ingest` sur l'hôte.

```yaml
# docker-compose.yml (cible)
services:
  api:
    build: apps/api
    environment: [RAG_TUTOR_OLLAMA_HOST=http://host.docker.internal:11434, ...]
    volumes: ["./chroma_db:/app/chroma_db:ro"]
    extra_hosts: ["host.docker.internal:host-gateway"]
    healthcheck: curl /api/health
  web:      { build: apps/web, healthcheck: wget / }
  nginx:    { image: nginx:alpine, ports: ["80:80","443:443"], depends_on: [api, web] }
```

⚠️ Chroma + multi-process : un seul worker Uvicorn (pas de `--workers 4`) tant que Chroma est embarqué sur un chemin partagé. GPU : inutile dans les containers au MVP (reranker CPU assumé, Ollama sur hôte).

---

# 13. Stratégie Nginx

Rôle : point d'entrée unique, terminaison TLS future, routage, et **contournement du buffering pour le SSE**.

```nginx
# infra/nginx/nginx.conf (cible, non créée maintenant)
upstream web { server web:3000; }
upstream api { server api:8000; }

server {
  listen 80;                       # 443 ssl + certbot en phase déploiement
  client_max_body_size 1m;

  location /api/ {
    proxy_pass http://api;         # le backend sert ses routes SOUS /api/* (préfixe assumé)
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    # --- indispensable pour SSE ---
    proxy_buffering off;
    proxy_cache off;
    proxy_read_timeout 300s;
    proxy_send_timeout 300s;
  }

  location / {
    proxy_pass http://web;
    proxy_set_header Host $host;
    # WebSocket upgrade (HMR dev, pas requis en prod)
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
  }
}
```

Décision : les routes FastAPI portent le préfixe `/api` nativement (`root_path` ou routes `/api/...`) → pas de rewrite fragile dans Nginx.

---

# 14. Tests

### Unitaires (pytest, sans Ollama/Chroma — rapides, CI-ables)
- `refusal_gate` : seuils, M1 auto-off si `RERANKER_ACTIVE=False`, refus sur hits vides.
- `retriever._rrf_fusion` / `children_to_parents` : fixtures en mémoire, α, dedup, ordre.
- `query_processing._parse` : JSON valide/malformé/bavard.
- `memory.ConversationMemory` : compression, élagage, bornes.
- `settings` : défauts = valeurs actuelles, override env.

### API (TestClient FastAPI)
- `/health` (Ollama mocké), `/chat` 200 avec pipeline mocké, 422 validation, 503 index absent, 502 Ollama KO, structure des sources conforme au schema.

### Intégration (manuel/scripté, nécessite Ollama + index)

```bash
curl -s localhost:8000/api/health | jq
curl -s -X POST localhost:8000/api/chat -H 'Content-Type: application/json' \
  -d '{"message":"Qu'"'"'est-ce qu'"'"'une cellule LSTM ?"}' | jq '.sources[0]'
curl -sN -X POST localhost:8000/api/chat/stream -d '{"message":"…"}'   # event: meta puis token*
```

### Test manuel utilisateur complet
1. Ouvrir `http://<hôte>` → UI du chat visible.
2. Poser « Qu'est-ce qu'un LSTM ? » → réponse ancrée avec citations.
3. Sources affichées sous la réponse (site/titre/section).
4. Poser une question hors corpus (« Quelle est la capitale du Japon ? ») → message de refus affiché clairement (badge), pas d'invention.
5. Poser un follow-up (« Et le GRU, comment le compare-t-on ? ») → l'anaphore est résolue (via history) — la réponse porte bien sur LSTM vs GRU.
6. Couper Ollama → erreur propre affichée dans l'UI, pas de crash.
7. Redémarrer → conversation continue côté frontend.

---

# 15. Risques techniques

| # | Risque | Impact | Mitigation |
|---|---|---|---|
| 1 | **Latence par requête élevée** (reformulation + retrieval + génération 14B + juge M2 : 30–90 s observables) | UX, timeouts | SSE (perçu plus rapide), timeouts alignés (Ollama/API/Nginx ≥ 120 s), `keep_alive=30m`, éventuellement `--no-query-processing` configurable |
| 2 | **Blocage event loop** (pipeline sync) | API gelée | Endpoints `def` (threadpool), itération stream via `iterate_in_threadpool` |
| 3 | **Concurrence** : BM25/CrossEncoder GIL-bound, Chroma embarqué mono-process | file d'attente | 1 worker assumé au MVP ; file d'attente Uvicorn ; documenter |
| 4 | **Aucun timeout Ollama aujourd'hui** | requêtes zombies | timeouts ajoutés au client (étape 9) |
| 5 | **M2 inactif en streaming** | risque hallucination > mode JSON | connu/assumé (le prompt d'ancrage reste) ; le mode JSON garde M2 |
| 6 | Réseau Docker→hôte (host.docker.internal Linux) | API ne voit pas Ollama | `extra_hosts: host-gateway`, testé étape 7 |
| 7 | Image torch volumineuse | build lent | base slim + wheel CPU, layer cache |
| 8 | `chroma_db` volumétrie/écritures concurrentes | corruption | volume :ro pour l'API, ingestion uniquement hôte |
| 9 | Régression RAG pendant le refactor config | qualité dégradée | défauts = valeurs actuelles exactes + CLI de régression + tests unitaires |

---

# 16. Estimation

| Phase | Complexité |
|---|---|
| 1. Settings + hygiène + tests de base | **Faible** |
| 2. FastAPI /health + /chat JSON | **Moyen** (mapping RAGResult, erreurs, concurrence) |
| 3–4. Next.js + intégration | **Moyen** |
| 5. SSE | **Moyen** (le backend existe déjà ; front + buffering à soigner) |
| 6. Docker | **Moyen** (torch image, host-gateway) |
| 7. Nginx + HTTPS | **Faible** |
| 8. Hardening + docs | **Faible** |

- **Prototype fonctionnel** (chat JSON + UI basique + intégration) : **2–3 jours**
- **MVP propre** (+ SSE, sources, erreurs, tests, config) : **4–6 jours**
- **MVP déployable** (+ Docker, Nginx, hardening, docs) : **6–9 jours**

Le poste le plus incertain est l'intégration du RAG existant sous charge réelle (latence, concurrence, réseau Docker→Ollama) — d'où un prototype tôt.

---

# 17. Definition of Done

```text
[ ] RAG existant conservé — aucun composant core/ réécrit
[ ] rag_tutor/settings.py : config par env, défauts identiques, make chat sans régression
[ ] evaluation/ hors du chemin runtime (import tutor découplé)
[ ] FastAPI : /api/health, /api/chat (JSON), schemas Pydantic, erreurs structurées
[ ] /api/chat/stream SSE : meta → tokens → done|error, non bufferisé
[ ] Next.js : chat multi-tours côté client, refus et erreurs affichés proprement
[ ] Sources affichées depuis hits[*].meta réels (label, url, section, pages)
[ ] ChromaDB : index existant consommé tel quel (8952 enfants / 1953 parents)
[ ] Ollama hôte utilisé, keep_alive, timeouts configurés
[ ] docker compose up → nginx + web + api opérationnels
[ ] Nginx route / et /api, SSE traverse sans buffering
[ ] Tests unitaires + API verts ; test d'intégration curl documenté
[ ] chroma_db/.deepeval déversionnés ; .env.example réel
[ ] README mis à jour (architecture MVP, run natif + Docker)
[ ] Ragas/DeepEval strictement hors application ; pas d'auth, pas d'upload, pas de persistance serveur
```

---

# 18. Première étape à implémenter

**Étape 1 — « Settings & fondations »** (aucune modification de logique RAG) :

1. Créer `src/rag_tutor/settings.py` : configuration centralisée lue depuis l'environnement, avec **exactement** les valeurs actuelles par défaut (`OLLAMA_HOST=http://127.0.0.1:11434`, `GEN_MODEL=qwen2.5:14b`, `JUDGE_MODEL=qwen3:8b`, `EMBEDDING_MODEL=bge-m3`, `RERANKER_MODEL=BAAI/bge-reranker-v2-m3`, `DB_DIR=chroma_db`, `COLLECTION_NAME=cours_ml_fig`, `RETRIEVAL_MODE=hybrid_rerank`, `RERANKER_REFUSAL_THRESHOLD=0.1119`, `MAX_TOKENS=900`, `NUM_CTX=24576`, `KEEP_ALIVE=30m`, + timeouts réseau).
2. Bascule des constantes de `core/llm_client.py`, `core/embeddings.py`, `core/vector_store.py`, `core/retriever.py`, `core/refusal_gate.py` vers ce module (lecture des attributs conservée pour compat).
3. Hygiène : `.gitignore += chroma_db/`, `git rm --cached chroma_db/chroma.sqlite3`, logging à la place des `print()` du chemin requête, `fastapi[standard]` ajouté à `pyproject.toml`.
4. Vérification : `make chat K=4 --show-sources` répond à l'identique ; premiers tests pytest (settings, refusal_gate) verts.

---

*Fin de l'audit — Phase 1. Aucune implémentation lancée sans autorisation explicite.*
