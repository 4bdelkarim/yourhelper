"use client";

import { useEffect, useRef, useState } from "react";
import ChatMessage, { Message } from "@/components/ChatMessage";
import { ApiError, HistoryTurn, sendChat } from "@/lib/api";

/**
 * Page de chat minimale — priorité fonctionnement > esthétique.
 *
 * Conversation 100 % côté React (aucune persistance serveur, aucun state
 * manager externe) :
 *   user message -> POST /api/chat (history = tours précédents)
 *                -> assistant response + sources -> messages[]
 *
 * Après chaque réponse, le tour est ajouté à l'historique (user + assistant),
 * ce qui permet au backend de résoudre les anaphores au tour suivant
 * (« Et comment le compare-t-on au GRU ? »).
 */
export default function HomePage() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [conversationId, setConversationId] = useState<string>("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, loading]);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const message = input.trim();
    if (!message || loading) return;

    const userMsg: Message = { role: "user", content: message };
    const history: HistoryTurn[] = messages
      .filter((m) => !m.refused)
      .map((m) => ({ role: m.role, content: m.content }));

    setMessages((prev) => [...prev, userMsg]);
    setInput("");
    setLoading(true);
    setError(null);

    try {
      const resp = await sendChat({
        message,
        conversationId: conversationId,
        history,
      });
      setConversationId(resp.conversation_id);
      setMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          content: resp.answer,
          refused: resp.refused,
          sources: resp.sources,
          latencyMs: resp.meta?.latency_ms,
        },
      ]);
    } catch (err) {
      const msg =
        err instanceof ApiError
          ? `${err.message}${err.code !== "http_error" ? ` (${err.code})` : ""}`
          : "Erreur inattendue.";
      setError(msg);
    } finally {
      setLoading(false);
    }
  }

  function resetConversation() {
    setMessages([]);
    setConversationId("");
    setError(null);
  }

  return (
    <main className="mx-auto flex h-screen max-w-3xl flex-col p-4">
      <header className="flex items-center justify-between border-b border-slate-200 pb-3">
        <div>
          <h1 className="text-xl font-bold">Tuteur Intelligent</h1>
          <p className="text-xs text-slate-500">
            Tuteur pédagogique RAG — réponses ancrées dans le corpus de cours
          </p>
        </div>
        <button
          onClick={resetConversation}
          className="rounded-lg border border-slate-300 px-3 py-1.5 text-sm text-slate-600 hover:bg-slate-200"
        >
          Nouvelle conversation
        </button>
      </header>

      <div className="flex-1 space-y-4 overflow-y-auto py-4">
        {messages.length === 0 && !loading && (
          <div className="mt-16 text-center text-slate-500">
            <p className="text-lg">
              Posez une question sur le cours de machine learning.
            </p>
            <p className="mt-2 text-sm">
              Exemple : « Qu&apos;est-ce qu&apos;un LSTM ? »
            </p>
          </div>
        )}

        {messages.map((m, i) => (
          <ChatMessage key={i} message={m} />
        ))}

        {loading && (
          <div className="flex justify-start">
            <div className="rounded-2xl bg-white px-4 py-3 shadow-sm">
              <p className="text-sm text-slate-500">
                Le tuteur réfléchit…
                <span className="ml-1 text-xs text-slate-400">
                  (recherche dans le corpus + génération locale, cela peut
                  prendre 30 à 90 s)
                </span>
              </p>
            </div>
          </div>
        )}

        {error && (
          <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800">
            <strong>Erreur : </strong>
            {error}
          </div>
        )}

        <div ref={bottomRef} />
      </div>

      <form onSubmit={handleSubmit} className="flex gap-2 border-t border-slate-200 pt-3">
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Votre question…"
          disabled={loading}
          maxLength={2000}
          className="flex-1 rounded-xl border border-slate-300 px-4 py-2.5 focus:border-blue-500 focus:outline-none disabled:opacity-50"
        />
        <button
          type="submit"
          disabled={loading || !input.trim()}
          className="rounded-xl bg-blue-600 px-5 py-2.5 font-medium text-white hover:bg-blue-700 disabled:opacity-50"
        >
          {loading ? "…" : "Envoyer"}
        </button>
      </form>
    </main>
  );
}
