"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Breadcrumb from "@/components/Breadcrumb";
import ChatMessage, { Message } from "@/components/ChatMessage";
import ConversationSidebar, { Conversation } from "@/components/ConversationSidebar";
import { ApiError, HistoryTurn, sendChatStream } from "@/lib/api";

/**
 * Page de chat — version SSE + UI institutionnelle.
 *
 * Conversations 100 % côté client (aucune persistance serveur, aucun state
 * manager externe) :
 *   - plusieurs conversations, listées dans la sidebar ; le fil actif vit
 *     dans l'état React, la liste est restaurée au chargement (localStorage).
 *   - pendant un tour : sources dès l'event `meta`, texte token par token,
 *     curseur clignotant (états explicites, jamais un spinner vague).
 *
 * L'historique transmis au backend (tours précédents, refus exclus) est
 * inchangé : la résolution des anaphores côté RAG est préservée.
 */

const STORAGE_KEY = "tuteur.conversations.v1";

interface StoredConversation {
  id: string;
  title: string;
  messages: Message[];
}

/** Charge les conversations sauvegardées (tolérant aux données corrompues). */
function loadConversations(): StoredConversation[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed.filter(
      (c): c is StoredConversation =>
        c && typeof c.id === "string" && Array.isArray(c.messages),
    );
    } catch {
    return [];
  }
}

export default function HomePage() {
  const [conversations, setConversations] = useState<StoredConversation[]>([]);
  const [activeId, setActiveId] = useState<string>("");
  const [input, setInput] = useState("");
  const [pending, setPending] = useState<Message | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);

  // --- Persistance locale (localStorage) ---
  useEffect(() => {
    const stored = loadConversations();
    setConversations(stored);
    if (stored.length > 0) setActiveId(stored[0].id);
  }, []);

  useEffect(() => {
    if (typeof window === "undefined") return;
    try {
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(conversations));
    } catch {
      /* quota dépassé : la session continue en mémoire */
    }
  }, [conversations]);

  // --- Conversation active (dérivé) ---
  const active = conversations.find((c) => c.id === activeId) ?? null;
  const messages = active?.messages ?? [];
  const topic = messages.find((m) => m.role === "user")?.content;

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, pending]);

  const appendToActive = useCallback(
    (msg: Message) =>
      setConversations((prev) =>
        prev.map((c) => (c.id === activeId ? { ...c, messages: [...c.messages, msg] } : c)),
      ),
    [activeId],
  );

  const startNewConversation = () => {
    // Une conversation vide existe déjà ? On la réutilise (pas de doublons).
    const empty = conversations.find((c) => c.messages.length === 0);
    if (empty) {
      setActiveId(empty.id);
    } else {
      const conv: StoredConversation = {
        id: crypto.randomUUID(),
        title: "Nouvelle conversation",
        messages: [],
      };
      setConversations((prev) => [conv, ...prev]);
      setActiveId(conv.id);
    }
    setInput("");
    setPending(null);
    setError(null);
    setSidebarOpen(false);
  };

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const message = input.trim();
    if (!message || pending) return;

    // Garantit une conversation active (au premier message).
    let convId = activeId;
    let history: HistoryTurn[];
    if (!active) {
      const conv: StoredConversation = {
        id: crypto.randomUUID(),
        title: message,
        messages: [],
      };
      convId = conv.id;
      setConversations((prev) => [conv, ...prev]);
      setActiveId(conv.id);
      history = [];
    } else {
      history = active.messages
        .filter((m) => !m.refused)
        .map((m) => ({ role: m.role, content: m.content }));
      if (active.title === "Nouvelle conversation") {
        setConversations((prev) =>
          prev.map((c) => (c.id === convId ? { ...c, title: message } : c)),
        );
      }
    }

    const userMsg: Message = { role: "user", content: message };
    const assistantMsg: Message = { role: "assistant", content: "" };

    appendToActive(userMsg);
    setInput("");
    setError(null);
    setPending({ ...assistantMsg });

    try {
      const { latencyMs } = await sendChatStream(
        { message, conversationId: convId, history },
        {
          onMeta: (meta) => {
            assistantMsg.refused = meta.refused;
            assistantMsg.sources = meta.sources;
            setPending({ ...assistantMsg });
          },
          onToken: (delta) => {
            assistantMsg.content += delta;
            setPending({ ...assistantMsg });
          },
        },
      );
      setPending(null);
      appendToActive({ ...assistantMsg, latencyMs });
    } catch (err) {
      // Erreur après ouverture du flux : les tokens déjà affichés sont conservés.
      setPending(null);
      if (assistantMsg.content) appendToActive({ ...assistantMsg });
      setError(
        err instanceof ApiError
          ? `${err.message}${err.code !== "http_error" ? ` (${err.code})` : ""}`
          : "Erreur inattendue.",
      );
    }
  }

  function resetConversation() {
    // Supprime la conversation active (à la demande, depuis la sidebar).
    setConversations((prev) => prev.filter((c) => c.id !== activeId));
    setActiveId("");
    setPending(null);
    setError(null);
  }

  return (
    <div className="flex h-screen">
      <ConversationSidebar
        conversations={conversations}
        activeId={activeId}
        onSelect={(id) => {
          setActiveId(id);
          setSidebarOpen(false);
        }}
        onNew={startNewConversation}
        open={sidebarOpen}
        onClose={() => setSidebarOpen(false)}
      />

      <main className="flex min-w-0 flex-1 flex-col">
        {/* Bandeau supérieur : hamburger (mobile) + fil contextuel + reset */}
        <header className="flex items-center justify-between gap-3 border-b border-slate-200 bg-white px-4 py-2.5">
          <div className="flex min-w-0 items-center gap-3">
            <button
              onClick={() => setSidebarOpen(true)}
              className="rounded-md border border-slate-300 p-2 text-slate-600 hover:bg-slate-100 md:hidden"
              aria-label="Ouvrir le menu des conversations"
              aria-expanded={sidebarOpen}
            >
              <svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden="true">
                <path d="M2 4h12M2 8h12M2 12h12" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
              </svg>
            </button>
            <Breadcrumb topic={topic} />
          </div>
          <button
            onClick={resetConversation}
            className="shrink-0 rounded-md border border-slate-300 px-3 py-1.5 text-xs text-slate-600 hover:bg-slate-100"
          >
            Supprimer la conversation
          </button>
        </header>

        {/* Fil de chat */}
        <div className="flex-1 space-y-4 overflow-y-auto bg-paper px-4 py-4">
          {messages.length === 0 && !pending && (
            <div className="mt-16 text-center text-slate-500">
              <p className="text-lg">Posez une question sur le cours de machine learning.</p>
              <p className="mt-2 text-sm">Exemple : « Qu&apos;est-ce qu&apos;un LSTM ? »</p>
            </div>
          )}

          {messages.map((m, i) => (
            <ChatMessage key={i} message={m} />
          ))}

          {pending && <ChatMessage message={pending} streaming />}

          {error && (
            <div
              role="alert"
              className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800"
            >
              <strong>Erreur : </strong>
              {error}
            </div>
          )}

          <div ref={bottomRef} />
        </div>

        {/* Saisie — fixe en bas */}
        <form
          onSubmit={handleSubmit}
          className="flex gap-2 border-t border-slate-200 bg-white px-4 py-3"
        >
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Votre question…"
            disabled={!!pending}
            maxLength={2000}
            aria-label="Votre question"
            className="flex-1 rounded-lg border border-slate-300 px-4 py-2.5 text-base focus:border-univ-700 focus:outline-none disabled:opacity-50"
          />
          <button
            type="submit"
            disabled={!!pending || !input.trim()}
            className="rounded-lg bg-univ-700 px-5 py-2.5 font-medium text-white hover:bg-univ-600 disabled:opacity-50"
          >
            {pending ? "…" : "Envoyer"}
          </button>
        </form>
      </main>
    </div>
  );
}
