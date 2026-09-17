#!/usr/bin/env python3
"""
refusal_gate.py — MECANISMES DE REFUS :

  1) RERANKER-based (pre-generation, zero cout supplementaire) :
     should_refuse_reranker(hits) → bool
     Utilise le score DU RERANKER (cross-encoder bge-reranker-v2-m3) pour
     decider si le contexte est pertinent. Le reranker est un bien meilleur
     juge de pertinence que le score cosine/BM25 — c'est litteralement sa
     fonction. Ne coute RIEN de plus puisqu'il tourne deja en hybrid_rerank.

  2) POST-generation (LLM judge) : verify_answer(question, answer, hits) → bool
     (defini dans generator.py) — un 2e LLM (qwen3:8b) verifie que la reponse
     est bien ancree dans le contexte fourni. Decide APRES la generation,
     plus fiable qu'un simple score de retrieval.

  NOTE : l'ancien mecanisme score-based (should_refuse, REFUSAL_THRESHOLD) a
  ete supprime (commit ~2026-08-06). Le score du meilleur hit de retrieval
  (RRF ou cosine) est un signal trop faible pour discriminer answerable /
  unanswerable sur ce dataset — le seuil etait au minimum theorique RRF et
  ne declenchait jamais. Le reranker le remplace avantageusement.

API publique :
  should_refuse_reranker(hits, threshold=RERANKER_REFUSAL_THRESHOLD) -> bool
  calibrate(scored_examples) -> tuple[float, float]   # (seuil optimal, accuracy)
"""

# =====================================================
# MECANISME 1 : score du reranker (pre-generation, cross-encoder)
# =====================================================

# Seuil sur le score du cross-encoder bge-reranker-v2-m3 en-dessous duquel on
# refuse de repondre. Le reranker donne des logits (pas des probabilites) —
# l'echelle approximative est [-10, +10], les scores > 0 indiquent une pertinence
# positive. Valeur CALIBREE via evaluation/calibrate.py sur eval/test_set_v2.json
# (mode hybrid_rerank) — cf. eval/reranker_calibration.json. Configurable via
# RERANKER_REFUSAL_THRESHOLD dans l'environnement (cf. ../settings.py).
from ..settings import RERANKER_REFUSAL_THRESHOLD


def should_refuse_reranker(hits: list[dict], threshold: float = RERANKER_REFUSAL_THRESHOLD) -> bool:
    """Refuse si le score du meilleur hit (score du reranker en mode hybrid_rerank,
    ou score RRF/cosine sinon) est sous le seuil. Ne coute rien : le reranker
    tourne deja dans hybrid_rerank, son score est dans ``hits[*]["dist"]``.

    Le meilleur score est cherche PARMI TOUS les hits, pas seulement le premier.
    C'est indispensable quand les hits proviennent d'une fusion round-robin
    multi sous-questions (pipeline.py) : ``hits[0]`` n'est alors pas forcement
    le mieux classe, contrairement au cas simple ou le retrieval est unique.

    En mode hybrid_rerank : ``hits[*]["dist"]`` = score du cross-encoder (logit).
    En mode hybrid : ``hits[*]["dist"]`` = score RRF (peu discriminant).
    En mode dense : ``hits[*]["dist"]`` = similarite cosinus.

    IMPORTANT : le seuil RERANKER_REFUSAL_THRESHOLD n'est calibre QUE pour les
    logits du cross-encoder (echelle [-10, +10]). Si le reranker est indisponible
    (retriever.RERANKER_ACTIVE=False), les hits portent des scores RRF/cosine
    (~0.01-0.1) qui seraient TOUJOURS sous le seuil -> refus systematique errone.
    Dans ce cas, on desactive le refus M1 (le M2 LLM-judge reste actif).

    Retourne True si la reponse doit ETRE REFUSEE (score < seuil)."""
    if not hits:
        return True
    try:
        from .retriever import RERANKER_ACTIVE
        if not RERANKER_ACTIVE:
            # Reranker absent -> scores non comparables au seuil calibre.
            # On ne refuse PAS sur ce signal degrade (le M2 tranchera).
            return False
    except ImportError:
        pass  # retriever non importable (ex. test unitaire) -> comportement historique

    # Chercher le MEILLEUR score parmi tous les hits, pas seulement hits[0].
    # hits[0] n'est le meilleur que dans le cas simple (retrieval unique trie).
    # Dans le cas round-robin multi sous-questions (pipeline.py), les hits sont
    # entrelaces et hits[0] n'est PAS forcement le mieux classe.
    top_score = max((h.get("dist", float("-inf")) for h in hits), default=None)
    if top_score is None:
        return False
    return top_score < threshold


# =====================================================
# CALIBRATION (generique — pour les trois mecanismes)
# =====================================================

def calibrate(scored_examples: list[tuple[float, bool]]) -> tuple[float, float]:
    """scored_examples : liste de (top_score, is_unanswerable: bool). Balaie les
    seuils possibles (chaque score observe) et renvoie celui qui maximise
    l'accuracy refus/reponse sur cet echantillon -- point de depart, pas
    scientifiquement optimal (pas de validation croisee), mais largement
    suffisant pour un seuil de decision simple comme celui-ci."""
    if not scored_examples:
        raise ValueError("scored_examples est vide -- rien a calibrer")

    candidates = sorted(set(s for s, _ in scored_examples))
    best_threshold, best_acc = candidates[0], -1.0
    for t in candidates:
        correct = sum(
            1 for score, is_unanswerable in scored_examples
            if (score < t) == is_unanswerable
        )
        acc = correct / len(scored_examples)
        if acc > best_acc:
            best_threshold, best_acc = t, acc
    return best_threshold, best_acc
