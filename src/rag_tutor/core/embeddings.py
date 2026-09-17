#!/usr/bin/env python3
"""
embeddings.py — SEULE RESPONSABILITE : transformer du texte en vecteurs.

Utilise bge-m3 servi par Ollama (100% local, ZERO requete HuggingFace).

IMPORTANT COHERENCE : ce module est le SEUL point d'entree pour l'embedding,
cote indexation (ingest.py) COMME cote retrieval (retriever.py). Les
deux doivent appeler EXACTEMENT la meme methode (Ollama /api/embed, meme
modele) -- sinon les vecteurs de requete et les vecteurs indexes ne vivent
plus dans le meme espace, SANS erreur visible, juste de mauvais resultats
de recherche. Ne jamais recreer une deuxieme implementation ailleurs :
retriever.py doit importer BGEEmbeddings d'ICI, pas en refaire une.
"""

from ..settings import EMBEDDING_MODEL, OLLAMA_HOST  # noqa: F401  (réexport pour compat)


class BGEEmbeddings:
    """bge-m3 servi par Ollama (deja pulled localement, cf. `ollama list`) --
    remplace l'ancien chemin sentence-transformers qui allait chercher les poids
    sur HuggingFace Hub (source du 401/RepositoryNotFoundError).

    Utilise ollama.embed() (endpoint /api/embed, RECENT) et non ollama.embeddings()
    (endpoint /api/embeddings, ANCIEN) : le premier accepte une LISTE de textes en
    un seul appel (vrai batch), le second un seul texte a la fois. Les vecteurs
    renvoyes par /api/embed sont DEJA normalises L2 cote serveur Ollama -> pas besoin
    de le refaire nous-memes (equivalent du normalize_embeddings=True d'avant).

    Client EXPLICITE (ollama.Client(host=...)), pas les fonctions globales
    ollama.embed()/ollama.chat() : celles-ci resolvent leur host via OLLAMA_HOST
    (variable d'env) ou un defaut interne a la lib, qui peut pointer ailleurs sans
    prevenir (port ngrok herite de Colab, instance orpheline...). Avec un Client
    explicite, AUCUNE ambiguite possible sur le serveur contacte."""

    def __init__(self, model: str = EMBEDDING_MODEL, host: str = OLLAMA_HOST) -> None:
        import ollama
        self._client = ollama.Client(host=host)
        self.model = model.split(":")[0]        # tolere qu'on lui passe "bge-m3:latest"

    def embed_documents(self, texts: list[str], batch_size: int = 16,
                        max_retries: int = 3) -> list[list[float]]:
        """batch_size reduit a 16 par defaut (etait 32) : sur un serveur Ollama
        partage/contraint, un gros lot peut faire planter la requete (OOM cote
        serveur -> connexion coupee en EOF, pas une erreur HTTP propre). En cas
        d'echec : retry avec backoff (transitoire -- charge du serveur partage),
        puis en dernier recours scission du lot en deux pour isoler un item
        precis (texte anormalement long/malformed) plutot que de tout arreter."""
        vectors, n, i = [], len(texts), 0
        while i < n:
            batch = texts[i:i + batch_size]
            try:
                vectors.extend(self._embed_batch(batch, max_retries))
            except RuntimeError as e:
                # Un item corrompu dans ce lot (texte trop long, malformed...)
                # -> on ajoute un vecteur zero pour maintenir l'alignement
                # et continuer l'indexation. L'indexation de TOUT le corpus
                # ne doit pas echouer a cause d'un seul texte defectueux.
                print(f"\n  [ERREUR] echec definitif d'embedding sur un lot de {len(batch)} : {e}")
                print(f"    -> vecteurs zeros inseres pour ce lot (poursuite de l'indexation)")
                # Determiner la dimension depuis les vecteurs deja produits
                dim = len(vectors[-1]) if vectors else 1024  # bge-m3 = 1024d
                vectors.extend([[0.0] * dim] * len(batch))
            i += len(batch)
            print(f"  embeddings Ollama ({self.model}) : {i}/{n}", end="\r", flush=True)
        print()  # newline apres la barre de progression en \r
        return vectors

    def _embed_batch(self, batch, max_retries):
        import time
        for attempt in range(max_retries):
            try:
                return self._client.embed(model=self.model, input=batch)["embeddings"]
            except Exception as e:
                if attempt < max_retries - 1:
                    wait = 2 ** attempt
                    print(f"\n  [avertissement] echec embedding (lot de {len(batch)}, "
                          f"tentative {attempt + 1}/{max_retries}) : {e} -- nouvel essai dans {wait}s")
                    time.sleep(wait)
        if len(batch) > 1:
            print(f"\n  [avertissement] lot de {len(batch)} toujours en echec apres "
                  f"{max_retries} essais -- scission en deux pour isoler le probleme")
            mid = len(batch) // 2
            return self._embed_batch(batch[:mid], max_retries) + self._embed_batch(batch[mid:], max_retries)
        print(f"\n  [ERREUR] impossible d'embedder ce texte meme seul ({max_retries} essais) : "
              f"{repr(batch[0][:150])}")
        raise RuntimeError(f"echec definitif d'embedding sur : {batch[0][:150]!r}")

    def embed_query(self, text: str) -> list[float]:
        """Embedde UNE requete dans le meme espace vectoriel que l'indexation.

        Args:
            text: Texte de la requete.

        Returns:
            Vecteur (deja normalise L2 cote serveur Ollama).
        """
        resp = self._client.embed(model=self.model, input=text)
        return resp["embeddings"][0]