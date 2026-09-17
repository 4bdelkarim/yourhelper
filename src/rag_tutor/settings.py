#!/usr/bin/env python3
"""
settings.py — SEUL point de configuration du package rag_tutor.

Toutes les constantes autrefois définies en tête des modules core (llm_client,
embeddings, vector_store, retriever, refusal_gate) sont lues ICI depuis
l'environnement, avec EXACTEMENT les valeurs actuelles comme défauts :
sans aucune variable d'env, le comportement est identique à l'avant-refactor
(zéro régression attendue, vérifié par tests + smoke test).

Ordre de lecture :
  1. un .env à la racine du projet est chargé (best-effort, sans dépendance
     externe, n'écrase JAMAIS une variable déjà présente dans l'environnement) ;
  2. chaque variable est lue via os.getenv avec sa valeur par défaut.

Les modules core continuent d'exposer les MÊMES noms d'attributs de module
(GEN_MODEL, OLLAMA_HOST, DB_DIR...) — ils les tirent simplement d'ici. Le
rest du code ne change pas (compat CLI/évaluation/rapports préservée).

Préfixe volontairement absent des noms (OLLAMA_HOST et non RAG_TUTOR_OLLAMA_HOST)
pour correspondre au .env.example historique ; les collisions avec d'autres
outils sont peu probables et le .env est local au projet.
"""

import os
from pathlib import Path


# ---------------------------------------------------------------------
# Chargement best-effort d'un fichier .env (racine du projet)
# ---------------------------------------------------------------------

def load_dotenv(path: str | Path = ".env") -> list[str]:
    """Charge KEY=VALUE depuis un fichier .env sans écraser l'environnement.

    Retourne la liste des clés effectivement chargées. Ne lève jamais :
    un .env malformé est ignoré (ligne par ligne) plutôt que bloquant.
    """
    loaded: list[str] = []
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except OSError:
        return loaded
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip("'\"")
        if not key or key in os.environ:
            continue  # n'écrase jamais une variable déjà définie
        os.environ[key] = value
        loaded.append(key)
    return loaded


# Le .env doit être lu AVANT les os.getenv ci-dessous (import du module).
load_dotenv()


def _env_str(name: str, default: str) -> str:
    value = os.getenv(name)
    return value if value not in (None, "") else default


def _env_opt(name: str) -> str | None:
    """Variable optionnelle : absente/vide -> None (pas de défaut actif)."""
    value = os.getenv(name)
    return value if value not in (None, "") else None


def _env_int(name: str, default: int) -> int:
    try:
        return int(_env_str(name, str(default)))
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(_env_str(name, str(default)))
    except ValueError:
        return default


# ---------------------------------------------------------------------
# Ollama
# ---------------------------------------------------------------------

# Instance Ollama principale — port 11434 confirmé actif. Le client explicite
# (ollama.Client(host=...)) utilise ce host EXACT, quoi que le reste de
# l'environnement essaie de résoudre en implicite (cf. commentaires historiques
# dans llm_client.py / embeddings.py).
OLLAMA_HOST = _env_str("OLLAMA_HOST", "http://127.0.0.1:11434")

# Timeout réseau (secondes) des appels Ollama. None (défaut) = AUCUN timeout,
# comportement historique du package. Une valeur (ex : 300) borne chaque
# requête HTTP : recommandé pour l'API, cf. audit §15 risque n°4.
OLLAMA_TIMEOUT: float | None = None
_timeout_raw = _env_opt("OLLAMA_TIMEOUT")
if _timeout_raw is not None:
    try:
        OLLAMA_TIMEOUT = float(_timeout_raw)
    except ValueError:
        OLLAMA_TIMEOUT = None

# ---------------------------------------------------------------------
# Modèles
# ---------------------------------------------------------------------

# qwen2.5:14b : génération. Differé du JUDGE_MODEL (bug historique Colab :
# juge et générateur confondus — ne JAMAIS fusionner ces deux valeurs).
GEN_MODEL = _env_str("GEN_MODEL", "qwen2.5:14b")
# qwen3:8b : juge M2 (verify_answer) + compression mémoire conversationnelle.
JUDGE_MODEL = _env_str("JUDGE_MODEL", "qwen3:8b")
# bge-m3 : embeddings via Ollama /api/embed — PAS un repo HuggingFace.
EMBEDDING_MODEL = _env_str("EMBEDDING_MODEL", "bge-m3")
# Cross-encoder hors Ollama (sentence-transformers, CPU) — cache HF requis
# au premier lancement (cf. make setup / scripts/fetch_reranker.py).
RERANKER_MODEL = _env_str("RERANKER_MODEL", "BAAI/bge-reranker-v2-m3")

# ---------------------------------------------------------------------
# Génération
# ---------------------------------------------------------------------

# 900 : 400 (contrainte historique CPU) coupait les réponses en plein mot ;
# remonter si des réponses restent tronquées sur des questions complexes.
MAX_TOKENS = _env_int("MAX_TOKENS", 900)
# 24576 (réduit de 32768) : économise ~25% de KV cache/slot, suffisant pour
# les parents retrouvés (max ~80K caractères). Remonter à 32768 si contexte
# coupé avant génération.
NUM_CTX = _env_int("NUM_CTX", 24576)
# keep_alive Ollama : réutilise le modèle entre requêtes (évite les cold starts).
KEEP_ALIVE = _env_str("KEEP_ALIVE", "30m")

# ---------------------------------------------------------------------
# ChromaDB (index persistant, client embarqué)
# ---------------------------------------------------------------------

# Chemin RELATIF au CWD : lancer uvicorn/CLI à la racine du projet
# (ou définir DB_DIR absolu). Volume Docker en phase 6.
DB_DIR = _env_str("DB_DIR", "chroma_db")
COLLECTION_NAME = _env_str("COLLECTION_NAME", "cours_ml_fig")

# ---------------------------------------------------------------------
# Retrieval
# ---------------------------------------------------------------------

# "dense" | "hybrid" | "hybrid_rerank" — hybrid_rerank = BM25 + dense + RRF
# + cross-encoder (comportement évalué, cf. evaluation/).
RETRIEVAL_MODE = _env_str("RETRIEVAL_MODE", "hybrid_rerank")

# Seuil de refus M1 sur le score du cross-encoder (logit, échelle ~[-10,+10]).
# Valeur CALIBRÉE via evaluation/calibrate.py sur eval/test_set_v2.json
# (mode hybrid_rerank) — cf. eval/reranker_calibration.json. NE PAS modifier
# à la main sans re-calibrer.
RERANKER_REFUSAL_THRESHOLD = _env_float("RERANKER_REFUSAL_THRESHOLD", 0.1119)

# ---------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------

# Niveau des logs rag_tutor (chemin requête : dégradation reranker, retries
# embeddings...). Remplace les print() historiques du chemin requête.
LOG_LEVEL = _env_str("LOG_LEVEL", "WARNING").upper()


def configure_logging(force: bool = False) -> None:
    """Configure le logging racine pour voir les logs rag_tutor.

    Idempotent (sauf force=True) : appelé au démarrage de l'API et
    disponible pour les CLI. WARNING par défaut — les avertissements du
    chemin requête restent visibles sans polluer (INFO/DEBUG = chat verbeux).
    """
    import logging
    root = logging.getLogger()
    if root.handlers and not force:
        return
    logging.basicConfig(
        level=LOG_LEVEL,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def as_dict() -> dict:
    """Vue complète de la configuration effective (diagnostic, /health, docs)."""
    return {
        "OLLAMA_HOST": OLLAMA_HOST,
        "OLLAMA_TIMEOUT": OLLAMA_TIMEOUT,
        "GEN_MODEL": GEN_MODEL,
        "JUDGE_MODEL": JUDGE_MODEL,
        "EMBEDDING_MODEL": EMBEDDING_MODEL,
        "RERANKER_MODEL": RERANKER_MODEL,
        "MAX_TOKENS": MAX_TOKENS,
        "NUM_CTX": NUM_CTX,
        "KEEP_ALIVE": KEEP_ALIVE,
        "DB_DIR": DB_DIR,
        "COLLECTION_NAME": COLLECTION_NAME,
        "RETRIEVAL_MODE": RETRIEVAL_MODE,
        "RERANKER_REFUSAL_THRESHOLD": RERANKER_REFUSAL_THRESHOLD,
        "LOG_LEVEL": LOG_LEVEL,
    }
