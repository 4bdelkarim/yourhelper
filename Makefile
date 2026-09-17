# Makefile — Tuteur RAG Pédagogique (rag-tutor v2.1.0)
# ============================================================
#
# Cibles principales :
#   make setup    — Installe les dépendances + vérifie l'environnement
#   make ingest   — Ingère le corpus (chunking + embedding + ChromaDB)
#   make chat     — Lance le CLI Q&A direct (mode évaluation)
#   make tutor    — Lance le CLI conversationnel socratique
#   make eval     — Lance l'évaluation complète (Ragas + retrieval)
#   make clean    — Nettoie l'index ChromaDB et les caches Python
#
# Usage :
#   make setup
#   make ingest DIR=data/normalized
#   make chat K=6
#   make tutor K=4 SHOW_SOURCES=--show-sources
#   make eval MODE=hybrid_rerank
#   make clean

.PHONY: help setup ingest chat tutor eval clean docker-build docker-up docker-down docker-logs docker-clean

# ============================================================
# CONFIG
# ============================================================

# Environnement Python : venv LOCAL du projet (.venv/), créé par `make setup`.
# Aucun chemin externe — le projet est autonome et fonctionne dès
# `git clone` + `make setup`.
# PIP_CONFIG_FILE=/dev/null : l'installation ignore toute config pip globale
# (même un pip.conf système malformé ne bloque plus `make setup`).
VENV        := .venv
VENV_PYTHON := $(VENV)/bin/python
VENV_PIP    := $(VENV)/bin/pip

# Venv local s'il existe, sinon retombée sur le python système.
ifeq ($(wildcard $(VENV_PYTHON)),)
  PYTHON := python3
else
  PYTHON := $(VENV_PYTHON)
endif
OLLAMA      := ollama

# Modèles Ollama requis
OLLAMA_MODELS := qwen2.5:14b qwen3:8b bge-m3

# Paramètres par défaut
K           ?= 4
DIR         ?= data/normalized
MODE        ?= hybrid_rerank
DATASET     ?= eval/golden_dataset_v2.json
SHOW_SOURCES ?=

# HF_HUB_OFFLINE desactive — le fallback automatique de retriever.py gere
# lesormais le cas "reranker absent" sans planter (degradation vers hybrid).
# Le reranker est charge normalement ; s'il manque, il est telecharge
# automatiquement au premier lancement (~600 Mo mis en cache).
export CUDA_VISIBLE_DEVICES=
export TQDM_DISABLE=1

# Couleurs
GREEN  := \033[0;32m
YELLOW := \033[1;33m
RED    := \033[0;31m
CYAN   := \033[0;36m
RESET  := \033[0m

# ============================================================
# DEFAULT
# ============================================================

help:
	@echo "$(CYAN)Tuteur RAG Pédagogique — Makefile$(RESET)"
	@echo ""
	@echo "$(GREEN)Cibles disponibles :$(RESET)"
	@echo "  make setup       Installe les dépendances + vérifie l'environnement"
	@echo "  make ingest      Ingère le corpus (chunking + embedding + ChromaDB)"
	@echo "  make chat        Lance le CLI Q&A direct (mode évaluation)"
	@echo "  make tutor       Lance le CLI conversationnel socratique"
	@echo "  make eval        Lance l'évaluation complète (Ragas + retrieval)"
	@echo "  make clean       Nettoie l'index ChromaDB et les caches"
	@echo "  make docker-up   Build + lance api:8000 et web:3000 en Docker"
	@echo "  make docker-down Stoppe les conteneurs Docker"
	@echo "  make docker-logs Suit les logs des conteneurs"
	@echo "  make docker-clean Supprime conteneurs + images Docker du projet"
	@echo ""
	@echo "$(YELLOW)Variables (avec valeurs par défaut) :$(RESET)"
	@echo "  DIR=$(DIR)            Dossier des fichiers .md à ingérer"
	@echo "  K=$(K)                  Nombre de passages récupérés"
	@echo "  MODE=$(MODE)       Mode de retrieval (dense|hybrid|hybrid_rerank)"
	@echo "  SHOW_SOURCES=$(SHOW_SOURCES)     $(GREEN)--show-sources$(RESET) pour afficher les sources"
	@echo ""
	@echo "$(CYAN)Exemples :$(RESET)"
	@echo "  make setup"
	@echo "  make ingest DIR=data/normalized"
	@echo "  make chat K=6"
	@echo "  make tutor K=4 SHOW_SOURCES=--show-sources"
	@echo "  make eval MODE=hybrid"

# ============================================================
# SETUP
# ============================================================

setup: _check-python _install-deps _check-ollama _check-models _check-reranker
	@echo ""
	@echo "$(GREEN)✅ Setup terminé. Lance 'make chat' ou 'make tutor'.$(RESET)"

_check-python:
	@echo "$(CYAN)[1/5] Vérification Python...$(RESET)"
	@$(PYTHON) --version || (echo "$(RED)❌ Python 3 introuvable. Installe python>=3.11$(RESET)" && exit 1)
	@$(PYTHON) -c "import sys; assert sys.version_info >= (3,11), 'Python >= 3.11 requis'" \
		|| (echo "$(RED)❌ Python >= 3.11 requis$(RESET)" && exit 1)
	@echo "   ✅ Python $(shell $(PYTHON) --version)"

_install-deps:
	@echo "$(CYAN)[2/5] Environnement Python + dépendances...$(RESET)"
	@if [ ! -x "$(VENV_PYTHON)" ]; then \
		echo "   Création du venv $(VENV)/ ..."; \
		python3 -m venv $(VENV); \
	fi
	@PIP_CONFIG_FILE=/dev/null $(VENV_PIP) install -e . -q
	@echo "   ✅ Dépendances installées dans $(VENV)/ (config pip globale ignorée)"

_check-ollama:
	@echo "$(CYAN)[3/5] Vérification Ollama...$(RESET)"
	@curl -s http://127.0.0.1:11434/api/tags > /dev/null 2>&1 \
		&& echo "   ✅ Ollama actif sur localhost:11434" \
		|| (echo "$(RED)❌ Ollama injoignable. Lance 'ollama serve' d'abord.$(RESET)" && exit 1)

_check-models:
	@echo "$(CYAN)[4/5] Vérification des modèles Ollama...$(RESET)"
	@for model in $(OLLAMA_MODELS); do \
		$(OLLAMA) list | grep -q $$model \
			&& echo "   ✅ $$model" \
			|| (echo "   $(YELLOW)⚠️  $$model absent → 'ollama pull $$model' requis$(RESET)"); \
	done

# Reranker HF (bge-reranker-v2-m3) : pré-téléchargement dans le cache local.
# Sans cette étape, le premier `make chat` téléchargerait ~600 Mo-1,2 Go SANS
# barre de progression (TQDM_DISABLE=1) et semblerait gelé. Ici on désactive
# TQDM_DISABLE le temps de l'étape : le téléchargement est visible.
# Une fois en cache, l'étape est quasi instantanée et ne touche plus au réseau.
_check-reranker:
	@echo "$(CYAN)[5/5] Reranker bge-reranker-v2-m3 (HuggingFace)...$(RESET)"
	@unset HF_HUB_OFFLINE TQDM_DISABLE; $(VENV_PYTHON) scripts/fetch_reranker.py

# ============================================================
# INGEST
# ============================================================

ingest: _check-dir
	@echo "$(CYAN)Ingestion du corpus : $(DIR)...$(RESET)"
	@$(PYTHON) -m rag_tutor.ingestion.ingest $(DIR)
	@echo ""
	@echo "$(GREEN)✅ Ingestion terminée. Lance 'make chat' ou 'make tutor'.$(RESET)"

_check-dir:
	@if [ ! -d "$(DIR)" ]; then \
		echo "$(RED)❌ Dossier '$(DIR)' introuvable.$(RESET)"; \
		echo "   Spécifie un dossier avec : make ingest DIR=chemin/vers/processed"; \
		exit 1; \
	fi
	@count=$$(find $(DIR) -name '*.md' 2>/dev/null | wc -l); \
	if [ $$count -eq 0 ]; then \
		echo "$(RED)❌ Aucun fichier .md dans '$(DIR)'.$(RESET)"; \
		exit 1; \
	fi
	@echo "   ✅ $(DIR) : $$(find $(DIR) -name '*.md' 2>/dev/null | wc -l) fichiers .md"

# ============================================================
# CHAT (Q&A direct)
# ============================================================

chat:
	@echo "$(CYAN)Lancement du chat Q&A direct...$(RESET)"
	@$(PYTHON) -m rag_tutor.cli.chat --k=$(K) $(SHOW_SOURCES)

# ============================================================
# TUTOR (conversationnel socratique)
# ============================================================

tutor:
	@echo "$(CYAN)Lancement du tuteur conversationnel socratique...$(RESET)"
	@$(PYTHON) -m rag_tutor.cli.tutor --k=$(K) $(SHOW_SOURCES)

# ============================================================
# EVAL
# ============================================================

eval:
	@echo "$(CYAN)Lancement de l'évaluation (mode=$(MODE))...$(RESET)"
	@$(PYTHON) -m rag_tutor.evaluation.evaluate $(DATASET) --retrieval-mode=$(MODE)

# ============================================================
# DOCKER (phase 6 — api:8000 + web:3000, Ollama sur l'hôte)
# ============================================================

# Prérequis : Ollama actif sur l'hôte (curl présent au setup), chroma_db/
# construit via `make ingest` (bind-mounté tel quel dans le conteneur).

docker-build:
	@echo "$(CYAN)Build des images Docker (api + web)...$(RESET)"
	docker compose build
	@echo "$(GREEN)✅ Images construites.$(RESET)"

docker-up:
	@echo "$(CYAN)Lancement : api:8000 (Ollama hôte via host.docker.internal) + web:3000$(RESET)"
	docker compose up -d --build
	@echo "$(GREEN)✅ Up. Healthcheck : http://localhost:8000/api/health — Web : http://localhost:3000$(RESET)"

docker-down:
	@echo "$(YELLOW)Arrêt des conteneurs...$(RESET)"
	docker compose down
	@echo "$(GREEN)✅ Down (chroma_db/ et .hf-cache/ préservés : volumes bind-mount).$(RESET)"

docker-logs:
	docker compose logs -f

docker-clean:
	@echo "$(YELLOW)Suppression conteneurs + images du projet...$(RESET)"
	docker compose down --rmi local --remove-orphans
	@echo "$(GREEN)✅ Nettoyage Docker terminé (chroma_db/ et .hf-cache/ intacts).$(RESET)"

# ============================================================
# CLEAN
# ============================================================

clean:
	@echo "$(YELLOW)Nettoyage...$(RESET)"
	@rm -rf chroma_db/
	@echo "   ✅ Index ChromaDB supprimé (chroma_db/)"
	@find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	@echo "   ✅ Caches Python supprimés (__pycache__/)"
	@find . -type f -name '*.pyc' -delete 2>/dev/null || true
	@echo "   ✅ Fichiers .pyc supprimés"
	@echo ""
	@echo "$(GREEN)✅ Nettoyage terminé.$(RESET)"
	@echo "   Pour réindexer : make ingest DIR=data/normalized"
