"""Tests unitaires purs — encodeur SSE et classification d'erreurs.

Sans FastAPI ni TestClient : verrouillent les briques réutilisées par les
deux modes (JSON et SSE) et la stabilité du format filaire.
"""

import ollama
import pytest
from fastapi import HTTPException

from apps.api.errors import error_payload, map_pipeline_exception
from apps.api.sse import sse_event, sse_lines


class TestSseEncoder:
    def test_single_event_format(self):
        assert sse_event("token", {"delta": "ok"}) == 'event: token\ndata: {"delta": "ok"}\n\n'

    def test_ascii_false_french_text(self):
        out = sse_event("token", {"delta": "é" * 3000})
        assert "é" in out  # ensure_ascii=False : UTF-8 direct, pas de \u00e9

    def test_multi_line_data_stays_on_one_line(self):
        # json.dumps échappe les \n littéraux en \n : la charge reste sur UNE
        # ligne \n, le framing SSE (event:/data:/ligne vide) n'est jamais cassé.
        out = sse_event("meta", {"rewritten_query": "ligne1\nligne2"})
        assert out.count("\n") == 3  # event: + data: + séparateur
        assert '\\n' in out          # le \n littéral est bien échappé dans le JSON

    def test_sse_lines_yields_each_event(self):
        out = list(sse_lines(iter([("meta", {"refused": False}), ("token", {"delta": "a"})])))
        assert out[0].startswith("event: meta\n")
        assert out[1].startswith("event: token\n")


class TestErrorPayload:
    def test_index_unavailable_file_not_found(self):
        code = error_payload(FileNotFoundError("parents_cours_ml_fig.json absent"))[1]
        assert code == "index_unavailable"

    def test_index_unavailable_runtime_error(self):
        status_code, code, _ = error_payload(RuntimeError("Collection Chroma [x] introuvable"))
        assert (status_code, code) == (503, "index_unavailable")

    def test_model_unavailable(self):
        status_code, code, msg = error_payload(RuntimeError("Le modele Ollama 'qwen3:8b' n'est pas disponible."))
        assert (status_code, code) == (502, "model_unavailable")
        assert "qwen3:8b" in msg  # ce message est réexpédié tel quel (actionnable)

    def test_ollama_unreachable(self):
        status_code, code, _ = error_payload(ollama.RequestError("connection refused"))
        assert (status_code, code) == (502, "ollama_unreachable")

    def test_unknown_is_generic(self):
        status_code, code, msg = error_payload(ValueError("mot de passe=abc"))
        assert (status_code, code) == (500, "internal_error")
        assert "mot de passe" not in msg  # détail interne jamais exposé

    def test_http_exception_mapping(self):
        exc = map_pipeline_exception(FileNotFoundError("parents absent"))
        assert isinstance(exc, HTTPException)
        assert exc.status_code == 503
        assert exc.detail["code"] == "index_unavailable"


class TestFailingStreamHelper:
    def test_yields_then_raises(self):
        from tests.conftest import FailingStream
        it = FailingStream(["a", "b"], RuntimeError("boom"))
        consumed = []
        with pytest.raises(RuntimeError, match="boom"):
            for tok in it:
                consumed.append(tok)
        assert consumed == ["a", "b"]  # yield les tokens puis lève
