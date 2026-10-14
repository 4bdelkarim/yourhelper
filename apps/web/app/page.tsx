"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { ArrowDown, Brain, Layers, Sigma } from "lucide-react";
import Breadcrumb from "@/components/Breadcrumb";
import ChatMessage, { Message } from "@/components/ChatMessage";
import ChatInput from "@/components/ChatInput";
import ConversationSidebar, { Conversation } from "@/components/ConversationSidebar";
import { ApiError, HistoryTurn, sendChatStream } from "@/lib/api";

/**
 * Page de chat — version SSE + UI portail institutionnel (inspiration ENT UCA).
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

/** Cartes de suggestions de l'accueil — questions réellement posables. */
const SUGGESTIONS = [
  { icon: Brain, label: "Qu'est-ce qu'un LSTM ?" },
  { icon: Sigma, label: "Expliquez la rétropropagation" },
  { icon: Layers, label: "Quelles différences entre GRU et LSTM ?" },
];

export default function HomePage() {
  const [conversations, setConversations] = useState<StoredConversation[]>([]);
  const [activeId, setActiveId] = useState<string>("");
  const [input, setInput] = useState("");
  const [pending, setPending] = useState<Message | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [atBottom, setAtBottom] = useState(true);
  const bottomRef = useRef<HTMLDivElement>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

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

  // --- Défilement : suit le streaming UNIQUEMENT si l'utilisateur est en bas.
  // Sinon, le bouton « Nouveau message » prend le relais (plus bas).
  const handleScroll = useCallback(() => {
    const el = scrollRef.current;
    if (!el) return;
    setAtBottom(el.scrollHeight - el.scrollTop - el.clientHeight < 80);
  }, []);

  useEffect(() => {
    if (!atBottom) return;
    const reduced =
      typeof window !== "undefined" &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    bottomRef.current?.scrollIntoView({
      behavior: reduced ? "auto" : "smooth",
      block: "end",
    });
  }, [messages, pending, atBottom]);

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

  async function send(message: string) {
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
    setAtBottom(true);
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

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    send(input.trim());
  }

  function resetConversation() {
    // Supprime la conversation active (à la demande, depuis la sidebar).
    deleteConversation(activeId);
  }

  function deleteConversation(id: string) {
    // Suppression définitive d'une conversation (corbeille de la sidebar).
    // Si c'est la conversation active, le fil se vide ; une génération en
    // cours n'a plus d'accroche d'affichage → pending est également levé
    // (le flux se termine en arrière-plan, ses tokens ne sont plus affichés).
    setConversations((prev) => prev.filter((c) => c.id !== id));
    if (id === activeId) {
      setActiveId("");
      setPending(null);
      setError(null);
    }
  }

  /** « Réessayer » : remet la dernière question dans la zone de saisie. */
  function retryLastQuestion() {
    const lastUser = [...messages].reverse().find((m) => m.role === "user");
    if (lastUser) setInput(lastUser.content);
    setError(null);
  }

  const showHero = messages.length === 0 && !pending;

  return (
    <div className="flex w-full min-h-0 flex-1">
      <ConversationSidebar
        conversations={conversations}
        activeId={activeId}
        onSelect={(id) => {
          setActiveId(id);
          setSidebarOpen(false);
        }}
        onNew={startNewConversation}
        onDelete={deleteConversation}
        open={sidebarOpen}
        onClose={() => setSidebarOpen(false)}
        collapsed={sidebarCollapsed}
        onToggleCollapsed={() => setSidebarCollapsed((v) => !v)}
      />

      <main
        id="contenu"
        tabIndex={-1}
        className="flex min-h-0 min-w-0 flex-1 flex-col focus:outline-none"
      >
        {/* Bandeau supérieur : hamburger (mobile) + fil contextuel + reset */}
        <header className="flex items-center justify-between gap-3 border-b border-border-soft bg-surface px-4 py-2.5">
          <div className="flex min-w-0 items-center gap-3">
            <button
              onClick={() => setSidebarOpen(true)}
              className="rounded-lg border border-border-soft p-2 text-ink-muted hover:bg-surface-alt md:hidden"
              aria-label="Ouvrir le menu des conversations"
              aria-expanded={sidebarOpen}
            >
              <svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden="true">
                <path
                  d="M2 4h12M2 8h12M2 12h12"
                  stroke="currentColor"
                  strokeWidth="1.5"
                  strokeLinecap="round"
                />
              </svg>
            </button>
            <Breadcrumb topic={topic} />
          </div>
          <button
            onClick={resetConversation}
            className="shrink-0 rounded-lg border border-border-soft px-3 py-1.5 text-xs text-ink-muted hover:bg-surface-alt hover:text-ink"
          >
            Supprimer la conversation
          </button>
        </header>

        {/* Fil de chat */}
        <div
          ref={scrollRef}
          onScroll={handleScroll}
          className="relative flex-1 overflow-y-auto bg-surface-alt px-4 py-6"
        >
          {showHero ? (
            /* --- Accueil (chat vide) : H1, explication, cartes --- */
            <div className="mx-auto w-full max-w-4xl py-6">
              <h1 className="text-3xl font-semibold tracking-tight text-ink">
                Tuteur Machine Learning
              </h1>
              <p className="mt-3 max-w-[65ch] text-base leading-relaxed text-ink-muted">
                Posez une question sur votre cours : les réponses sont issues
                des supports du cours (PDF et pages web), avec sources citées.
              </p>

              <h2 className="mt-10 text-lg font-semibold text-ink">
                Pour commencer
              </h2>
              <div className="mt-4 grid gap-3 sm:grid-cols-2">
                {SUGGESTIONS.map(({ icon: Icon, label }) => (
                  <button
                    key={label}
                    onClick={() => send(label)}
                    disabled={!!pending}
                    className="group flex items-start gap-3 rounded-lg border border-border-soft bg-surface p-4 text-left transition hover:border-brand hover:shadow-sm disabled:opacity-50"
                  >
                    <span
                      aria-hidden="true"
                      className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-brand-soft text-brand"
                    >
                      <Icon className="h-5 w-5" strokeWidth={1.75} />
                    </span>
                    <span className="text-sm font-medium leading-snug text-ink group-hover:text-brand-ink">
                      {label}
                    </span>
                  </button>
                ))}

                {/* Carte « Comment ça marche ? » — explicative, non cliquable. */}
                <div className="rounded-lg border border-brand-border bg-brand-soft p-4 sm:col-span-2">
                  <h3 className="text-sm font-semibold text-brand-ink">
                    Comment ça marche ?
                  </h3>
                  <ul className="mt-2 space-y-1.5 text-sm leading-relaxed text-ink-muted">
                    <li className="flex items-start gap-2">
                      <span aria-hidden="true" className="mt-2 h-1 w-1 shrink-0 rounded-full bg-brand" />
                      Le tuteur recherche dans le corpus du cours et cite ses
                      sources pour chaque affirmation.
                    </li>
                    <li className="flex items-start gap-2">
                      <span aria-hidden="true" className="mt-2 h-1 w-1 shrink-0 rounded-full bg-brand" />
                      Si le sujet ne figure pas dans les supports, il le dit
                      clairement plutôt que d&apos;inventer une réponse.
                    </li>
                  </ul>
                </div>
              </div>
            </div>
          ) : (
            /* --- Fil de conversation --- */
            <div className="mx-auto w-full max-w-4xl space-y-4">
              {messages.map((m, i) => (
                <ChatMessage key={i} message={m} />
              ))}

              {pending && <ChatMessage message={pending} streaming />}

              <div ref={bottomRef} />
            </div>
          )}

          {error && (
            <div
              role="alert"
              className="mx-auto mt-4 flex w-full max-w-4xl items-start justify-between gap-3 rounded-lg border border-danger-border bg-danger-soft px-4 py-3 text-sm text-danger-text"
            >
              <p>
                <strong>Erreur : </strong>
                {error}
              </p>
              <button
                onClick={retryLastQuestion}
                className="shrink-0 rounded-lg border border-danger-border px-3 py-1.5 text-xs font-medium text-danger-text hover:bg-danger-soft/70"
              >
                Réessayer
              </button>
            </div>
          )}

          {/* Revenir en bas pendant un streaming suivi depuis plus haut. */}
          {pending && !atBottom && (
            <div className="pointer-events-none sticky bottom-4 z-10 flex justify-center">
              <button
                onClick={() => {
                  setAtBottom(true);
                  bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
                }}
                className="pointer-events-auto flex items-center gap-1.5 rounded-lg bg-ink px-3.5 py-2 text-xs font-medium text-surface shadow-lg"
              >
                <ArrowDown className="h-3.5 w-3.5" strokeWidth={2} aria-hidden="true" />
                Nouveau message
              </button>
            </div>
          )}
        </div>

        {/* Saisie — fixe en bas, section « Poser une question » */}
        <section
          aria-labelledby="poser-question"
          className="border-t border-border-soft bg-surface px-4 py-3 pb-[env(safe-area-inset-bottom)]"
        >
          <h2 id="poser-question" className="sr-only">
            Poser une question
          </h2>
          <div className="mx-auto w-full max-w-4xl">
            <ChatInput
              value={input}
              onChange={setInput}
              onSubmit={handleSubmit}
              disabled={!!pending}
            />
            <p className="mt-2 text-xs text-ink-muted">
              Les réponses sont générées à partir des supports du cours et
              citent leurs sources. Vérifiez les informations importantes.
            </p>
          </div>
        </section>
      </main>
    </div>
  );
}
