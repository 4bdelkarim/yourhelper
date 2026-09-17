#!/usr/bin/env python3
"""
llm_client.py — SEULE RESPONSABILITE : appeler le LLM de generation (Qwen2.5 via
Ollama) avec un system prompt + un message utilisateur, et renvoyer le texte.

Utilise par query_processing.py (reformulation/decomposition) ET generator.py
(reponse finale) -- UN SEUL point d'entree, pour ne jamais avoir deux facons
differentes d'appeler Ollama qui pourraient diverger (modele, temperature...).

IMPORTANT : evaluate.py (le JUGE) ne doit JAMAIS appeler ce module avec
GEN_MODEL -- le bug JUDGE_MODEL/GEN_MODEL confondus sur Colab vient de la, donc
le juge doit passer son propre modele explicitement via le parametre `model`
de chat(), jamais en dependant du defaut ci-dessous.

Client EXPLICITE (ollama.Client(host=...)), pas la fonction globale ollama.chat() :
celle-ci resout son host via OLLAMA_HOST (variable d'env) ou un defaut interne a
la lib, qui peut pointer ailleurs sans prevenir (port herite d'un tunnel ngrok
Colab, instance orpheline sur un port aleatoire...). Avec un Client explicite,
AUCUNE ambiguite sur le serveur contacte -- cf. embeddings.py, meme principe.
"""

from collections.abc import Iterator

from ..settings import (
    GEN_MODEL,
    KEEP_ALIVE,
    MAX_TOKENS,
    NUM_CTX,
    OLLAMA_HOST,
    OLLAMA_TIMEOUT,
)

# Configuration (modèles, limites, host, timeout) : voir ../settings.py — SEUL
# point de configuration du package, lu depuis l'environnement (défauts =
# valeurs historiques). Les noms sont réexportés ici pour compat totale avec
# le code existant (CLI, évaluation, API) qui lit GEN_MODEL, OLLAMA_HOST, etc.


def chat(system_prompt: str, user_message: str, model: str = GEN_MODEL,
         temperature: float = 0.2, max_tokens: int = MAX_TOKENS,
         host: str = OLLAMA_HOST, num_ctx: int | None = NUM_CTX,
         keep_alive: str = KEEP_ALIVE) -> str:
    """Appel simple : system + user -> texte de reponse (pas de streaming, pas d'historique).

    Parametres
    ----------
    num_ctx : int
        Taille de la fenetre de contexte en tokens (passe dans les options Ollama).
        Reduit de 32768 (defaut modele) a 24576 par defaut pour economiser du KV
        cache. Mettre None pour utiliser le defaut du modele."""
    import ollama
    # OLLAMA_TIMEOUT (settings.py) : None = comportement historique sans
    # timeout ; valeur définie -> transmise au client (kwargs httpx).
    client_kwargs = {"host": host}
    if OLLAMA_TIMEOUT is not None:
        client_kwargs["timeout"] = OLLAMA_TIMEOUT
    client = ollama.Client(**client_kwargs)
    opts = {"temperature": temperature, "num_predict": max_tokens}
    if num_ctx is not None:
        opts["num_ctx"] = num_ctx
    try:
        resp = client.chat(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            options=opts,
            keep_alive=keep_alive,
        )
        return resp["message"]["content"]
    except Exception as e:
        msg = str(e).lower()
        is_missing_model = "not found" in msg or ("model" in msg and ("not" in msg or "no" in msg))
        if is_missing_model:
            raise RuntimeError(
                f"Le modele Ollama '{model}' n'est pas disponible.\n"
                f"  Verifie avec : ollama list\n"
                f"  Si absent, telecharge-le : ollama pull {model}"
            ) from e
        raise

def chat_stream(system_prompt: str, user_message: str, model: str = GEN_MODEL,
                temperature: float = 0.2, max_tokens: int = MAX_TOKENS,
                host: str = OLLAMA_HOST, num_ctx: int | None = NUM_CTX,
                keep_alive: str = KEEP_ALIVE) -> Iterator[str]:
    """Version streaming de chat() : yield chaque token des qu'il est genere par Ollama.
    Meme signature que chat(), mais retourne un generateur de str.

    Usage :
        for token in chat_stream(system, user):
            print(token, end="", flush=True)
    """
    import ollama
    client_kwargs = {"host": host}
    if OLLAMA_TIMEOUT is not None:
        client_kwargs["timeout"] = OLLAMA_TIMEOUT
    client = ollama.Client(**client_kwargs)
    opts = {"temperature": temperature, "num_predict": max_tokens}
    if num_ctx is not None:
        opts["num_ctx"] = num_ctx
    stream = client.chat(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
        options=opts,
        stream=True,
        keep_alive=keep_alive,
    )
    for chunk in stream:
        content = chunk.get("message", {}).get("content", "")
        if content:
            yield content
