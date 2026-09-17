"""Tests du contrat JSON — POST /api/chat.

Verrouillent le contrat du prototype : réponse conforme au schéma, sources
construites depuis les hits réels via citation_label(), history sérialisée au
format pipeline (user -> Étudiant, assistant -> Tuteur), validation Pydantic,
erreurs structurées {code, message}.
"""

from apps.api.schemas.chat import ChatRequest
from tests.conftest import FakeResult, REFUSAL, make_hit, make_web_hit


class TestContract:
    def test_200_contract(self, client, fake_pipeline):
        fake_pipeline(FakeResult(hits=[make_hit(), make_web_hit()], answer="Le LSTM est un réseau récurrent."))
        resp = client.post("/api/chat", json={"message": "Qu'est-ce qu'un LSTM ?"})

        assert resp.status_code == 200
        body = resp.json()
        assert body["answer"] == "Le LSTM est un réseau récurrent."
        assert body["refused"] is False
        assert body["conversation_id"]  # uuid généré si absent de la requête
        # citation_label() ne répète pas le titre de page quand il coïncide
        # avec le titre de section (comportement réel du RAG, non modifié).
        assert {s["label"] for s in body["sources"]} == {
            "pdf · 05_RNN.pdf · §3.1- LSTM",                     # via citation_label()
            "web · d2l.ai · §10.1. Long Short-Term Memory (LSTM)",
        }
        assert body["meta"]["rewritten_query"] == "question reformulée"
        assert isinstance(body["meta"]["latency_ms"], int)

    def test_refusal_verbatim(self, client, fake_pipeline):
        fake_pipeline(FakeResult(hits=[make_hit()], answer=REFUSAL, refused=True))
        resp = client.post("/api/chat", json={"message": "Capitale du Japon ?"})

        assert resp.status_code == 200
        body = resp.json()
        assert body["refused"] is True
        assert body["answer"] == REFUSAL
        assert len(body["sources"]) == 1  # hits renvoyés pour transparence

    def test_conversation_id_preserved(self, client, fake_pipeline):
        fake_pipeline(FakeResult(hits=[]))
        cid = "b7e2c1a0-0000-4000-8000-000000000001"
        body = client.post(
            "/api/chat",
            json={"message": "suite", "conversation_id": cid},
        ).json()
        assert body["conversation_id"] == cid

    def test_contract_sources_schema(self, client, fake_pipeline):
        fake_pipeline(FakeResult(hits=[make_hit()]))
        body = client.post("/api/chat", json={"message": "q"}).json()
        (source,) = body["sources"]
        assert set(source) == {
            "label", "source", "source_type", "source_url", "title",
            "source_id", "section", "page_start", "page_end", "score",
        }
        assert source["page_start"] == 4 and source["page_end"] == 5
        assert source["source_url"] is None  # PDF : pas d'URL (jamais inventé)


class TestPipelineCall:
    def test_history_format(self, client, fake_pipeline):
        answer = fake_pipeline(FakeResult(hits=[]))
        client.post(
            "/api/chat",
            json={
                "message": "Et le GRU ?",
                "history": [
                    {"role": "user", "content": "Qu'est-ce qu'un LSTM ?"},
                    {"role": "assistant", "content": "Le LSTM est…"},
                ],
            },
        )
        (query, kwargs), = answer.calls
        assert query == "Et le GRU ?"
        assert kwargs["history"] == (
            "[DERNIERS ÉCHANGES]\n"
            "Étudiant : Qu'est-ce qu'un LSTM ?\n"
            "Tuteur : Le LSTM est…"
        )
        assert kwargs["stream"] is False

    def test_k_forwarded(self, client, fake_pipeline):
        answer = fake_pipeline(FakeResult(hits=[]))
        client.post("/api/chat", json={"message": "q", "k": 7})
        assert answer.calls[0][1]["k"] == 7


class TestValidation:
    def test_empty_message_422(self, client, fake_pipeline):
        fake_pipeline(FakeResult(hits=[]))
        assert client.post("/api/chat", json={"message": ""}).status_code == 422

    def test_too_long_message_422(self, client, fake_pipeline):
        fake_pipeline(FakeResult(hits=[]))
        assert client.post("/api/chat", json={"message": "x" * 2001}).status_code == 422

    def test_bad_history_role_422(self, client, fake_pipeline):
        fake_pipeline(FakeResult(hits=[]))
        resp = client.post(
            "/api/chat",
            json={"message": "q", "history": [{"role": "system", "content": "x"}]},
        )
        assert resp.status_code == 422

    def test_k_out_of_range_422(self, client, fake_pipeline):
        fake_pipeline(FakeResult(hits=[]))
        assert client.post("/api/chat", json={"message": "q", "k": 9}).status_code == 422


class TestErrors:
    def test_503_index_unavailable(self, client, fake_pipeline):
        fake_pipeline(RuntimeError("Collection Chroma [cours_ml_fig] introuvable."))
        resp = client.post("/api/chat", json={"message": "q"})
        assert resp.status_code == 503
        assert resp.json()["detail"] == {
            "code": "index_unavailable",
            "message": "L'index du corpus n'est pas disponible. "
                       "Lancez d'abord : make ingest DIR=data/normalized",
        }

    def test_502_model_unavailable(self, client, fake_pipeline):
        fake_pipeline(RuntimeError("Le modele Ollama 'qwen2.5:14b' n'est pas disponible."))
        resp = client.post("/api/chat", json={"message": "q"})
        assert resp.status_code == 502
        assert resp.json()["detail"]["code"] == "model_unavailable"

    def test_502_ollama_unreachable(self, client, fake_pipeline):
        import ollama
        fake_pipeline(ollama.RequestError("connection refused"))
        resp = client.post("/api/chat", json={"message": "q"})
        assert resp.status_code == 502
        assert resp.json()["detail"]["code"] == "ollama_unreachable"

    def test_500_unknown_not_leaked(self, client, fake_pipeline):
        fake_pipeline(ValueError("secret interne: /etc/passwd"))
        resp = client.post("/api/chat", json={"message": "q"})
        assert resp.status_code == 500
        assert "secret" not in resp.json()["detail"]["message"]


class TestRequestModel:
    def test_defaults(self):
        req = ChatRequest(message="q")
        assert req.k == 4 and req.history == [] and req.conversation_id is None
