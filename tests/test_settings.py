"""Tests de src/rag_tutor/settings.py — le contrat du refactor phase 1.

Sans réseau, sans modèle, sans index : la config est du pur Python.
Deux garanties verrouillées :
  1. SANS variable d'env : défauts = valeurs historiques EXACTES (zéro
     régression RAG — risque n°9 de l'audit) ;
  2. AVEC variable d'env : la valeur d'env gagne (prérequis Docker —
     OLLAMA_HOST=host.docker.internal en phase 6).
"""

import importlib

import pytest

import src.rag_tutor.settings as settings
from src.rag_tutor import settings as settings_module


# ---------------------------------------------------------------------
# 1. Défauts = valeurs historiques exactes
# ---------------------------------------------------------------------

class TestDefaults:
    def test_defaults_match_historical_values(self, monkeypatch):
        """Sanctuaire : toute dérive de ces défauts doit échouer volontairement."""
        for name in ("OLLAMA_HOST", "GEN_MODEL", "JUDGE_MODEL", "EMBEDDING_MODEL",
                     "RERANKER_MODEL", "MAX_TOKENS", "NUM_CTX", "KEEP_ALIVE",
                     "DB_DIR", "COLLECTION_NAME", "RETRIEVAL_MODE",
                     "RERANKER_REFUSAL_THRESHOLD", "OLLAMA_TIMEOUT"):
            monkeypatch.delenv(name, raising=False)
        monkeypatch.chdir(".")  # .env absent à la racine ? -> défauts purs
        fresh = importlib.reload(settings)
        try:
            assert fresh.OLLAMA_HOST == "http://127.0.0.1:11434"
            assert fresh.GEN_MODEL == "qwen2.5:14b"
            assert fresh.JUDGE_MODEL == "qwen3:8b"
            assert fresh.EMBEDDING_MODEL == "bge-m3"
            assert fresh.RERANKER_MODEL == "BAAI/bge-reranker-v2-m3"
            assert fresh.MAX_TOKENS == 900
            assert fresh.NUM_CTX == 24576
            assert fresh.KEEP_ALIVE == "30m"
            assert fresh.DB_DIR == "chroma_db"
            assert fresh.COLLECTION_NAME == "cours_ml_fig"
            assert fresh.RETRIEVAL_MODE == "hybrid_rerank"
            assert fresh.RERANKER_REFUSAL_THRESHOLD == pytest.approx(0.1119)
            assert fresh.OLLAMA_TIMEOUT is None  # comportement historique : pas de timeout
        finally:
            importlib.reload(settings)

    def test_as_dict_covers_all_settings(self):
        d = settings.as_dict()
        assert d["GEN_MODEL"] == settings.GEN_MODEL
        assert d["OLLAMA_TIMEOUT"] == settings.OLLAMA_TIMEOUT
        assert len(d) == 14  # 13 réglages + LOG_LEVEL


# ---------------------------------------------------------------------
# 2. Override par variable d'environnement
# ---------------------------------------------------------------------

class TestEnvOverride:
    def test_ollama_host_override(self, monkeypatch):
        monkeypatch.setenv("OLLAMA_HOST", "http://host.docker.internal:11434")
        fresh = importlib.reload(settings)
        try:
            assert fresh.OLLAMA_HOST == "http://host.docker.internal:11434"
        finally:
            importlib.reload(settings)

    def test_timeout_override_parses_float(self, monkeypatch):
        monkeypatch.setenv("OLLAMA_TIMEOUT", "300")
        fresh = importlib.reload(settings)
        try:
            assert fresh.OLLAMA_TIMEOUT == 300.0
        finally:
            importlib.reload(settings)

    def test_invalid_timeout_falls_back_to_none(self, monkeypatch):
        monkeypatch.setenv("OLLAMA_TIMEOUT", "not-a-number")
        fresh = importlib.reload(settings)
        try:
            assert fresh.OLLAMA_TIMEOUT is None
        finally:
            importlib.reload(settings)

    def test_empty_value_means_default(self, monkeypatch):
        monkeypatch.setenv("OLLAMA_HOST", "")
        fresh = importlib.reload(settings)
        try:
            assert fresh.OLLAMA_HOST == "http://127.0.0.1:11434"
        finally:
            importlib.reload(settings)

    def test_float_threshold_override(self, monkeypatch):
        monkeypatch.setenv("RERANKER_REFUSAL_THRESHOLD", "0.25")
        fresh = importlib.reload(settings)
        try:
            assert fresh.RERANKER_REFUSAL_THRESHOLD == pytest.approx(0.25)
        finally:
            importlib.reload(settings)


# ---------------------------------------------------------------------
# 3. Chargement du fichier .env (best-effort, sans écraser l'env)
# ---------------------------------------------------------------------

class TestDotenv:
    def test_loads_simple_keys(self, tmp_path, monkeypatch):
        env_file = tmp_path / ".env"
        env_file.write_text(
            "# commentaire\nGEN_MODEL=qwen2.5:3b\n\nOLLAMA_HOST = 'http://10.0.0.5:11434'\n",
            encoding="utf-8",
        )
        monkeypatch.delenv("GEN_MODEL", raising=False)
        monkeypatch.delenv("OLLAMA_HOST", raising=False)
        loaded = settings.load_dotenv(env_file)
        assert "GEN_MODEL" in loaded and "OLLAMA_HOST" in loaded
        # load_dotenv peuple os.environ (les attributs du module, eux, sont
        # figés à l'import) — c'est l'environnement que lit un re-import.
        import os
        assert os.environ["OLLAMA_HOST"] == "http://10.0.0.5:11434"  # quotes retirés
        assert os.environ["GEN_MODEL"] == "qwen2.5:3b"
        monkeypatch.delenv("GEN_MODEL", raising=False)
        monkeypatch.delenv("OLLAMA_HOST", raising=False)

    def test_never_overrides_existing_env(self, tmp_path, monkeypatch):
        env_file = tmp_path / ".env"
        env_file.write_text("GEN_MODEL=petit-modele\n", encoding="utf-8")
        monkeypatch.setenv("GEN_MODEL", "deja-defini")
        loaded = settings.load_dotenv(env_file)
        assert "GEN_MODEL" not in loaded
        import os
        assert os.environ["GEN_MODEL"] == "deja-defini"  # env prioritaire sur .env

    def test_missing_file_is_silent(self, tmp_path):
        assert settings.load_dotenv(tmp_path / "absent.env") == []

    def test_malformed_lines_ignored(self, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text("pas-un-kv\n===\nOK=1\n", encoding="utf-8")
        loaded = settings.load_dotenv(env_file)
        assert loaded == ["OK"]


# ---------------------------------------------------------------------
# 4. Compat : les modules core exposent toujours les mêmes attributs
# ---------------------------------------------------------------------

class TestCoreModulesCompatibility:
    """Le reste du code (CLI, évaluation, API) lit GEN_MODEL, OLLAMA_HOST...
    comme attributs de module — la bascule vers settings ne doit rien casser."""

    def test_llm_client_reexports(self):
        from src.rag_tutor.core import llm_client
        assert llm_client.GEN_MODEL == settings_module.GEN_MODEL
        assert llm_client.OLLAMA_HOST == settings_module.OLLAMA_HOST
        assert llm_client.MAX_TOKENS == settings_module.MAX_TOKENS
        assert llm_client.NUM_CTX == settings_module.NUM_CTX
        assert llm_client.KEEP_ALIVE == settings_module.KEEP_ALIVE

    def test_vector_store_reexports(self):
        from src.rag_tutor.core import vector_store
        assert vector_store.DB_DIR == settings_module.DB_DIR
        assert vector_store.COLLECTION_NAME == settings_module.COLLECTION_NAME

    def test_retriever_mode_comes_from_settings(self):
        from src.rag_tutor.core import retriever
        assert retriever.MODE == settings_module.RETRIEVAL_MODE

    def test_refusal_gate_threshold_shared(self):
        from src.rag_tutor.core import refusal_gate
        assert refusal_gate.RERANKER_REFUSAL_THRESHOLD == \
            settings_module.RERANKER_REFUSAL_THRESHOLD

    def test_signatures_keep_historical_defaults(self):
        """Les signatures publiques ne changent pas (compat appelants)."""
        import inspect
        from src.rag_tutor.core.llm_client import chat, chat_stream
        for fn in (chat, chat_stream):
            sig = inspect.signature(fn)
            assert sig.parameters["keep_alive"].default == "30m"
            assert sig.parameters["temperature"].default == 0.2
