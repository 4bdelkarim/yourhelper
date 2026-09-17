"""Tests du flux SSE — POST /api/chat/stream.

Verrouillent le contrat de flux de la phase 5 :
  ordre meta -> token* -> done, format filaire text/event-stream, refus M1
  sans token, erreurs avant ouverture (HTTP) vs pendant le flux (event error),
  en-têtes anti-buffering.
"""

from apps.api.routes.chat import MEDIA_TYPE_SSE, SSE_HEADERS
from tests.conftest import FailingStream, FakeResult, REFUSAL, make_hit


class TestHappyPath:
    def test_order_meta_tokens_done(self, client, fake_pipeline, parse_sse):
        fake_pipeline(FakeResult(hits=[make_hit()], stream=["Un", " LSTM", " est", " un", " réseau", "."]))
        resp = client.post("/api/chat/stream", json={"message": "Qu'est-ce qu'un LSTM ?"})

        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith(MEDIA_TYPE_SSE)
        events = parse_sse(resp.text)
        assert [e for e, _ in events] == ["meta", "token", "token", "token", "token", "token", "token", "done"]

        (meta_event, meta), *rest = events
        assert meta["refused"] is False
        assert meta["rewritten_query"] == "question reformulée"
        assert meta["sources"][0]["label"] == "pdf · 05_RNN.pdf · §3.1- LSTM"
        assert "".join(d["delta"] for e, d in rest if e == "token") == "Un LSTM est un réseau."
        done = events[-1][1]
        assert isinstance(done["latency_ms"], int)

    def test_wire_format(self, client, fake_pipeline):
        """Le format filaire réel : event:/data: sur une ligne, blocs séparés par \\n\\n."""
        fake_pipeline(FakeResult(hits=[make_hit()], stream=["ok"]))
        resp = client.post("/api/chat/stream", json={"message": "q"})
        assert "event: token\ndata: {\"delta\": \"ok\"}\n\n" in resp.text

    def test_antibuffering_headers(self, client, fake_pipeline):
        fake_pipeline(FakeResult(hits=[make_hit()], stream=["x"]))
        resp = client.post("/api/chat/stream", json={"message": "q"})
        for key, value in SSE_HEADERS.items():
            assert resp.headers[key] == value


class TestRefusal:
    def test_refused_meta_done_no_token(self, client, fake_pipeline, parse_sse):
        fake_pipeline(FakeResult(hits=[make_hit()], answer=REFUSAL, refused=True))
        resp = client.post("/api/chat/stream", json={"message": "Capitale du Japon ?"})

        events = parse_sse(resp.text)
        assert [e for e, _ in events] == ["meta", "done"]
        (meta_event, meta), (done_event, done) = events
        assert meta["refused"] is True
        assert meta["sources"][0]["label"] == "pdf · 05_RNN.pdf · §3.1- LSTM"
        assert "latency_ms" in done


class TestStreamErrors:
    def test_error_before_headers_stays_http(self, client, fake_pipeline):
        """Erreur en phase bloquante (index) : HTTP 503, le flux n'est JAMAIS ouvert."""
        fake_pipeline(RuntimeError("Collection Chroma [cours_ml_fig] introuvable."))
        resp = client.post("/api/chat/stream", json={"message": "q"})
        assert resp.status_code == 503
        assert resp.json()["detail"]["code"] == "index_unavailable"

    def test_error_mid_stream_is_event(self, client, fake_pipeline, parse_sse):
        """Erreur pendant la génération (en-têtes déjà partis) : event error structuré,
        les tokens déjà émis restent dans le flux."""
        import ollama
        fake_pipeline(FakeResult(
            hits=[make_hit()],
            stream=FailingStream(["début", " visible…"], ollama.RequestError("boom")),
        ))
        resp = client.post("/api/chat/stream", json={"message": "q"})
        assert resp.status_code == 200  # flux déjà ouvert

        events = parse_sse(resp.text)
        assert [e for e, _ in events] == ["meta", "token", "token", "error"]
        (error_event, err) = events[-1]
        assert err["code"] == "ollama_unreachable"
        assert err["status"] == 502
        assert "message" in err

    def test_validation_422_like_json_route(self, client, fake_pipeline):
        fake_pipeline(FakeResult(hits=[]))
        assert client.post("/api/chat/stream", json={"message": ""}).status_code == 422


class TestPipelineCall:
    def test_stream_mode_requested(self, client, fake_pipeline):
        answer = fake_pipeline(FakeResult(hits=[], stream=["x"]))
        client.post("/api/chat/stream", json={"message": "Et le GRU ?"})
        (query, kwargs), = answer.calls
        assert kwargs["stream"] is True
