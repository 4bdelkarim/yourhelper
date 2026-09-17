#!/usr/bin/env python3
"""
retriever.py — SEULE RESPONSABILITE : recuperation hybride (BM25 + dense
+ rerank) sur la base deja indexee par ingest.py.

Chaine complete (ce que le systeme utilise vraiment) :
  BM25 (sparse) + dense (bge-m3, via embeddings.py) sur les ENFANTS
   -> fusion / dedup
   -> reranker cross-encoder (bge-reranker)      [precision fine, query-aware]
   -> remontee aux PARENTS uniques (bornes)      [contexte complet pour le LLM]

Ce module NE CONSTRUIT RIEN : la base Chroma et le magasin des parents sont lus
via vector_store.py (get_collection / load_parents), et l'embedding de requete
via embeddings.py (BGEEmbeddings) -- exactement les memes fonctions qu'a
l'indexation. DB_DIR/COLLECTION/EMBED_MODEL ne sont donc plus dupliques ici :
le bug qu'il fallait avant "corriger" a la main (base ou modele qui divergeait
entre ingestion et retrieval, sans erreur visible) ne peut structurellement
plus se reproduire.

Expose retrieve(question, k, source_type=None) -> liste de hits au format attendu
par evaluate.py / pipeline.py :
  {"text": <parent>, "dist": <score>,
   "meta": {source, source_type, page, page_start, page_end, section, parent_id}}

MODE (pour l'ablation du chapitre 6) : "dense" | "hybrid" | "hybrid_rerank"
  dense          = recuperation dense seule (baseline)
  hybrid         = + BM25 (fusion)
  hybrid_rerank  = + reranker cross-encoder   <-- pipeline final

RERANKER (a savoir) : Ollama n'expose que la couche d'embedding de ses modeles,
jamais la tete de classification qu'un cross-encoder utilise -> AUCUN contournement
propre cote Ollama a ce jour. bge-reranker-v2-m3 continue donc de passer par
sentence-transformers/HuggingFace (telechargement UNIQUE ~600 Mo au premier lancement,
mis en cache localement). Si le reranker est indisponible, le systeme degrade
AUTOMATIQUEMENT vers le mode hybrid (sans crash) — cf. RERANKER_ACTIVE.
Si tu veux zero HF (100% hors-ligne), passe MODE="hybrid" au prix de la qualite
(fidelite ~0.88 avec reranker vs ~0.69 sans, cf. trajectoire du chapitre 6).

Prerequis : python -m rag_tutor.ingestion.ingest data/normalized/   (cree chroma_db + parents_*.json)
Dependances : rank-bm25, sentence-transformers (deps du projet, cf. pyproject.toml)
"""

import logging

from ..settings import RERANKER_MODEL, RETRIEVAL_MODE
from .vector_store import get_collection, load_parents
from .embeddings import BGEEmbeddings

logger = logging.getLogger(__name__)

# =====================================================
# CONFIG (retrieval uniquement -- DB_DIR/COLLECTION/EMBED_MODEL viennent
# desormais de vector_store.py / embeddings.py, plus dupliques ici)
# =====================================================

# bge-reranker-v2-m3 : multilingue -> meilleur en FR. Cache HF requis au
# premier lancement (aucune alternative Ollama native). Valeur lue depuis
# settings (env RERANKER_MODEL), réexportée ici pour compat.
MODE = RETRIEVAL_MODE   # "dense" | "hybrid" | "hybrid_rerank"
BM25_K            = 20                # candidats BM25
DENSE_K           = 20                # candidats denses
RERANK_CANDIDATES = 40                # plafond de paires passees au reranker
FINAL_CHILDREN    = 18                # enfants gardes apres rerank (avant remontee parents)
RRF_K             = 60                # constante RRF (Reciprocal Rank Fusion) pour le mode hybrid
RRF_ALPHA         = 0.6               # ponderation dense vs BM25 dans le RRF : α=1 = 100% dense, α=0 = 100% BM25
                                      #   α=0.6 = leger avantage au dense (meilleur en single-passage semantique)
                                      #   α=0.5 = poids egaux (RRF classique)

# --- singletons charges paresseusement ---
_EMBEDDER = _COLL = _PAR = _BM25 = _DOCS = _METAS = _RERANK = None
# Sentinel pour distinguer "pas encore charge" de "charge echouee"
_RERANK_UNAVAILABLE = False
# Flag PUBLIC : indique si le reranker cross-encoder est reellement actif.
# refusal_gate.py (M1) s'en sert pour savoir si le score `dist` des hits est un
# logit cross-encoder (comparables au seuil calibre) ou un score RRF/cosine
# (incomparable -> le refus M1 doit etre desactive).
RERANKER_ACTIVE = True


def _lazy():
    global _EMBEDDER, _COLL, _PAR, _BM25, _DOCS, _METAS
    if _COLL is not None:
        return
    from rank_bm25 import BM25Okapi
    _EMBEDDER = BGEEmbeddings()                 # meme modele/methode qu'a l'indexation
    _COLL = get_collection()                    # meme base que l'indexation (vector_store.py)
    _PAR = load_parents()                        # meme magasin de parents (vector_store.py)
    got = _COLL.get(include=["documents", "metadatas"])
    _DOCS, _METAS = got["documents"], got["metadatas"]
    _BM25 = BM25Okapi([d.lower().split() for d in _DOCS])   # BM25 sur les ENFANTS


def _reranker():
    global _RERANK, _RERANK_UNAVAILABLE, RERANKER_ACTIVE
    if _RERANK is not None:
        return _RERANK
    if _RERANK_UNAVAILABLE:
        return None

    import sys, time
    from sentence_transformers import CrossEncoder

    last_error = None
    for attempt in range(1, 4):  # 3 tentatives (backoff : 3s, 6s, 9s)
        try:
            # device="cpu" explicite : evite l'appel a torch.cuda.is_available() qui
            # emet un UserWarning "driver NVIDIA trop ancien" sur cette machine
            # (CUDA indisponible ici, le reranker tourne sur CPU de toute facon).
            _RERANK = CrossEncoder(RERANKER_MODEL, device="cpu")
            # Verification minimale : le modele doit pouvoir predire un score
            _RERANK.predict([("test", "test")])
            return _RERANK
        except OSError as e:
            last_error = e
            err = str(e)
            # LocalEntryNotFoundError = cache absent/incomplet + pas de reseau
            # = CrossEncoder n'a pas pu downloader les poids manquants
            if "does not appear to have a file" in err or "no file named" in err:
                # Le cache est incomplet. On le purge pour forcer un retry propre
                # au prochain essai (sinon le cache corrompu bloque tous les retries).
                import shutil
                cache = (
                    __import__("pathlib").Path.home()
                    / ".cache" / "huggingface" / "hub"
                    / "models--BAAI--bge-reranker-v2-m3"
                )
                if cache.exists():
                    try:
                        shutil.rmtree(cache)
                    except Exception:
                        pass
                if attempt < 3:
                    wait = 3 * attempt
                    logger.warning(
                        "[retry %d/3] Cache corrompu purge, nouvelle tentative dans %ds...",
                        attempt, wait,
                    )
                    time.sleep(wait)
                    continue
            elif attempt < 3:
                wait = 3 * attempt
                logger.warning(
                    "[retry %d/3] Echec de chargement du reranker (%s), "
                    "nouvelle tentative dans %ds...", attempt, e, wait,
                )
                time.sleep(wait)
                continue
        except Exception as e:
            last_error = e
            if attempt < 3:
                wait = 3 * attempt
                logger.warning(
                    "[retry %d/3] Erreur inattendue du reranker "
                    "(%s: %s), nouvelle tentative dans %ds...",
                    attempt, type(e).__name__, e, wait,
                )
                time.sleep(wait)
                continue

    # Toutes les tentatives ont echoue -> degradation definitive
    _RERANK_UNAVAILABLE = True
    RERANKER_ACTIVE = False
    logger.warning(
        "Reranker '%s' INDISPONIBLE apres 3 tentatives (derniere erreur : "
        "%s: %s). DEGRADATION AUTOMATIQUE vers le mode 'hybrid' (fusion RRF "
        "sans rerank) : qualite reduite (~0.69 au lieu de ~0.88), le systeme "
        "fonctionne. Retablir : 1) connexion Internet, 2) python "
        "scripts/fetch_reranker.py, 3) pip install --upgrade "
        "sentence-transformers transformers.",
        RERANKER_MODEL, type(last_error).__name__, last_error,
    )
    return None


# =====================================================
# RECHERCHES ELEMENTAIRES (sur les enfants)
# =====================================================

def _dense(q, k, source_type=None):
    where = {"source_type": source_type} if source_type else None
    res = _COLL.query(query_embeddings=[_EMBEDDER.embed_query(q)], n_results=k,
                      include=["documents", "metadatas", "distances"], where=where)
    out = []
    for d, m, dist in zip(res["documents"][0], res["metadatas"][0], res["distances"][0]):
        out.append({"text": d, "meta": m or {}, "score": 1.0 - float(dist)})  # cosine -> similarite
    return out


def _bm25_search(q, k, source_type=None):
    scores = _BM25.get_scores(q.lower().split())
    idx = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)
    if source_type:
        idx = [i for i in idx if (_METAS[i] or {}).get("source_type") == source_type]
    idx = idx[:k]
    return [{"text": _DOCS[i], "meta": _METAS[i] or {}, "score": float(scores[i])} for i in idx]


def merge_dedup(a: list[dict], b: list[dict]) -> list[dict]:
    """Fusionne deux listes d'enfants en dedupliquant (parent_id + texte)."""
    seen, out = set(), []
    for r in a + b:
        key = (r["meta"].get("parent_id"), hash(r["text"]))
        if key in seen:
            continue
        seen.add(key); out.append(r)
    return out


def _rrf_fusion(dense_results, bm25_results, k=RRF_K, top_n=FINAL_CHILDREN, alpha=None):
    """Reciprocal Rank Fusion pondere : combine deux classements (dense + BM25)
    en utilisant le rang de chaque document, pas son score brut — resout le
    probleme d'echelles incomparables (cosinus ∈ [0,1] vs BM25 raw).

    RRF score = α·1/(k + rang_dense) + (1-α)·1/(k + rang_bm25)

    alpha=None → RRF classique (α=0.5, poids egaux) — retrocompatible.
    alpha=1.0 → 100% dense, alpha=0.0 → 100% BM25.
    Un document present dans les deux listes est naturellement booste.
    Retourne top_n candidats tries par score RRF decroissant."""
    if alpha is None:
        alpha = 0.5   # RRF classique : poids egaux
    rrf_scores = {}
    cand_by_key = {}

    for rank, c in enumerate(dense_results):
        pid = c["meta"].get("parent_id")
        key = (pid, hash(c["text"]))
        rrf_scores[key] = rrf_scores.get(key, 0.0) + alpha / (k + rank + 1)
        cand_by_key[key] = c

    for rank, c in enumerate(bm25_results):
        pid = c["meta"].get("parent_id")
        key = (pid, hash(c["text"]))
        rrf_scores[key] = rrf_scores.get(key, 0.0) + (1.0 - alpha) / (k + rank + 1)
        cand_by_key[key] = c

    sorted_keys = sorted(rrf_scores, key=rrf_scores.get, reverse=True)
    # On conserve le score RRF dans le champ "score" pour tracabilite (utile
    # pour children_to_parents -> "dist", et pour le refusal_gate s'il lit
    # le score du meilleur hit — meme si en pratique le seuil reste a recalibrer).
    out = []
    for key in sorted_keys[:top_n]:
        c = dict(cand_by_key[key])          # copie defensive : ne mute pas les listes d'origine
        c["score"] = rrf_scores[key]
        out.append(c)
    return out


def _rerank(q, cands, top_k):
    rk = _reranker()
    if rk is None:
        # Reranker indisponible -> on conserve l'ordre RRF deja calcule (fallback).
        # Les candidats arrivent deja tries par score RRF (cf. _rrf_fusion).
        return cands[:top_k]
    pool = cands[:RERANK_CANDIDATES]
    scores = rk.predict([(q, c["text"]) for c in pool])
    for c, s in zip(pool, scores):
        c["score"] = float(s)
    return sorted(pool, key=lambda x: x["score"], reverse=True)[:top_k]


# =====================================================
# REMONTEE AUX PARENTS (dedup, ordre = rang des enfants)
# =====================================================

def children_to_parents(cands: list[dict], parents: dict, k: int) -> list[dict]:
    """Remonte les enfants (dedupliques) vers leurs PARENTS uniques.

    Le premier enfant d'une section fournit son score (``dist``) au parent ;
    les enfants suivants de la meme section sont ignores (dedup). L'ordre des
    parents suit le rang des enfants.

    Args:
        cands: Enfants tries par pertinence.
        parents: Magasin des sections ``{parent_id -> {...}}``.
        k: Nombre maximal de parents a renvoyer.

    Returns:
        Liste de hits parents ``{text, dist, meta}``.
    """
    hits, seen = [], set()
    for c in cands:
        pid = c["meta"].get("parent_id")
        if pid is None or pid in seen or pid not in parents:
            continue
        seen.add(pid)
        par = parents[pid]
        hits.append({
            "text": par["text"], "dist": c.get("score"),
            "meta": {"source": par["source"],
                     "source_type": par.get("source_type"),   # propage pdf/web
                     "source_url": par.get("source_url"),     # site (web) pour les citations
                     "title": par.get("title"),               # titre de la page (web)
                     "source_id": par.get("source_id"),       # nom du fichier PDF
                     "page": par["page_start"],
                     "page_start": par["page_start"], "page_end": par["page_end"],
                     "section": par["section"], "parent_id": pid},
        })
        if len(hits) >= k:
            break
    return hits


# =====================================================
# API PRINCIPALE
# =====================================================

def retrieve(question: str, k: int = 4, final_children: int = FINAL_CHILDREN,
             source_type: str | None = None) -> list[dict]:
    """Recupere jusqu'a k PARENTS via la chaine choisie (MODE).
    source_type='pdf'|'web' filtre optionnellement -> diagnostic PDF vs web.

    MODES :
      dense         = dense seul, tri par similarite cosinus
      hybrid        = RRF (Reciprocal Rank Fusion) dense + BM25 — corrige le bug
                      d'echelles incomparables (cosinus vs BM25 raw) identifie au
                      Run 3, qui faisait du BM25 pur au lieu d'une vraie fusion.
      hybrid_rerank = fusion + reranker cross-encoder (rescorage uniforme)"""
    _lazy()

    if MODE == "dense":
        cands = _dense(question, DENSE_K, source_type=source_type)
        cands = sorted(cands, key=lambda x: x["score"], reverse=True)[:final_children]
    elif MODE == "hybrid":
        dense_results = _dense(question, DENSE_K, source_type=source_type)
        bm25_results = _bm25_search(question, BM25_K, source_type=source_type)
        cands = _rrf_fusion(dense_results, bm25_results, top_n=final_children, alpha=RRF_ALPHA)
    else:   # hybrid_rerank
        # RRF pondere (α=RRF_ALPHA) en amont du reranker : remplace le merge_dedup()
        # naif qui concatenait sans tri. Le RRF donne au reranker un pool de
        # candidats deja tries par pertinence, que le cross-encoder n'a plus qu'a
        # raffiner avec son score de similarite fine question↔passage.
        dense_results = _dense(question, DENSE_K, source_type=source_type)
        bm25_results = _bm25_search(question, BM25_K, source_type=source_type)
        cands = _rrf_fusion(dense_results, bm25_results, top_n=RERANK_CANDIDATES, alpha=RRF_ALPHA)
        cands = _rerank(question, cands, final_children)

    return children_to_parents(cands, _PAR, k)


if __name__ == "__main__":
    import sys
    q = sys.argv[1] if len(sys.argv) > 1 else "qu'est-ce qu'une cellule LSTM ?"
    print(f"MODE = {MODE}\nQuestion : {q}\n")
    for h in retrieve(q, k=6):
        m = h["meta"]
        print(f"[{m['source']} ({m.get('source_type','?')}) | {m['section']} | "
              f"p{m['page_start']}-{m['page_end']} | score={h['dist']:.3f}]")
        print(h["text"][:300], "…\n")