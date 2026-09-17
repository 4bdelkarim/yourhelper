"use client";

import { useEffect, useRef, useState } from "react";
import ChatMessage, { Message } from "@/components/ChatMessage";
import { ApiError, HistoryTurn, sendChatStream } from "@/lib/api";

/**
 * Page de chat — version SSE (phase 5).
 *
 * Conversation 100 % côté React (aucune persistance serveur, aucun state
 * manager externe). Différence avec la version JSON :
 *   - les tokens sont affichés AU FUR ET À MESURE (sendChatStream) ;
 *   - les sources s'affichent dès l'event `meta` (fin du retrieval, avant le
 *     premier token) — plus d'attente de 30-90 s sans feedback ;
 *   - un tour refusé arrive aussi en `meta` (refused:true, aucun token).
 *
 * L'historique transmis au backend reste identique (tours précédents, refus
 * exclus) : la résolution des anaphores côté RAG est inchangée.
 */
export default function HomePage() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [conversationId, setConversationId] = useState<string>("");
  const [pending, setPending] = useState<Message | null>(null);
  const [error, setError] = useState<string | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, pending]);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const message = input.trim();
    if (!message || pending) return;

    const userMsg: Message = { role: "user", content: message };
    const history: HistoryTurn[] = messages
      .filter((m) => !m.refused)
      .map((m) => ({ role: m.role, content: m.content }));

    // Objet LOCAL accumulé par les handlers SSE (appelés séquentiellement
    // pendant l'await). Les updaters React restent purs : aucun setState
    // imbriqué dans un updater — React StrictMode (dev) invoque les updaters
    // deux fois, ce qui dupliquait la promotion finale du message.
    const assistantMsg: Message = { role: "assistant", content: "" };

    setMessages((prev) => [...prev, userMsg]);
    setInput("");
    setError(null);
    // Tour en cours : les sources arriveront avec `meta`, le texte token par token.
    setPending({ ...assistantMsg });

    try {
      const { latencyMs } = await sendChatStream(
        {
          message,
          conversationId: conversationId,
          history,
        },
        {
          onMeta: (meta) => {
            assistantMsg.refused = meta.refused;
            assistantMsg.sources = meta.sources;
            setConversationId(meta.conversation_id);
            setPending({ ...assistantMsg });
          },
          onToken: (delta) => {
            assistantMsg.content += delta;
            setPending({ ...assistantMsg });
          },
        },
      );
      // Flux terminé : UNE seule promotion, via des updaters purs.
      setPending(null);
      setMessages((prev) => [...prev, { ...assistantMsg, latencyMs }]);
    } catch (err) {
      // Erreur après ouverture du flux : garder les tokens déjà affichés.
      setPending(null);
      if (assistantMsg.content) {
        setMessages((prev) => [...prev, { ...assistantMsg }]);
      }
      const msg =
        err instanceof ApiError
          ? `${err.message}${err.code !== "http_error" ? ` (${err.code})` : ""}`
          : "Erreur inattendue.";
      setError(msg);
    }
  }

  function resetConversation() {
    setMessages([]);
    setConversationId("");
    setPending(null);
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
        {messages.length === 0 && !pending && (
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

        {pending && (
          <ChatMessage message={pending} streaming />
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
          disabled={!!pending}
          maxLength={2000}
          className="flex-1 rounded-xl border border-slate-300 px-4 py-2.5 focus:border-blue-500 focus:outline-none disabled:opacity-50"
        />
        <button
          type="submit"
          disabled={!!pending || !input.trim()}
          className="rounded-xl bg-blue-600 px-5 py-2.5 font-medium text-white hover:bg-blue-700 disabled:opacity-50"
        >
          {pending ? "…" : "Envoyer"}
        </button>
      </form>
    </main>
  );
}
