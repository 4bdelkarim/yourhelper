"""Encodage des événements SSE (Server-Sent Events).

Contrat de flux POST /api/chat/stream — cf. audit-rag-tutor-v2.md §8/§11 :

    event: meta     data: {"conversation_id":"…","sources":[…],"refused":false,
                           "rewritten_query":"…","sub_queries":[…]}
    event: token    data: {"delta":"La backprop"}
    event: token    data: {"delta":"agation …"}
    event: done     data: {"latency_ms":8400}
    event: error    data: {"code":"ollama_unreachable","message":"…"}

`meta` est émis dès que le retrieval est terminé (avant le premier token) :
le frontend peut afficher les sources immédiatement. En cas de refus M1,
`meta` porte refused:true et `done` suit sans aucun token.

Format filaire (spécification text/event-stream) :
    <nom-event>\n
    data: <charge JSON sur UNE ligne, sans \n littéral>\n
    \n
Les charges sont sérialisées avec ensure_ascii=False (UTF-8 déclaré dans le
Content-Type) et sans espaces superflus. Aucun champ n'est ajouté ni retiré
selon le mode : le contrat est identique pour tous les clients.
"""

import json
from collections.abc import Iterator


def sse_event(event: str, data: dict) -> str:
    """Encode un événement SSE : `event:` + `data:` (JSON une ligne) + ligne vide."""
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def sse_lines(events: Iterator[tuple[str, dict]]) -> Iterator[str]:
    """Itère sur des couples (nom d'événement, charge) et produit le filaire SSE."""
    for event, data in events:
        yield sse_event(event, data)
