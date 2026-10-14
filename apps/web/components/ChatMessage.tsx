"use client";

import { motion, useReducedMotion } from "framer-motion";
import { GraduationCap } from "lucide-react";
import ReactMarkdown from "react-markdown";
import type { Source } from "@/lib/api";
import RefusalBadge from "./RefusalBadge";
import SourceList from "./SourceList";

export interface Message {
  role: "user" | "assistant";
  content: string;
  refused?: boolean;
  sources?: Source[];
  latencyMs?: number;
}

/** Indicateur d'attente « Le tuteur recherche dans le cours… » — 3 points animés. */
function SearchingDots() {
  return (
    <p className="flex items-center gap-2 text-sm text-ink-muted">
      Le tuteur recherche dans le cours…
      <span aria-hidden="true" className="flex items-center gap-1">
        <span className="typing-dot inline-block h-1 w-1 rounded-full bg-brand" />
        <span className="typing-dot inline-block h-1 w-1 rounded-full bg-brand" />
        <span className="typing-dot inline-block h-1 w-1 rounded-full bg-brand" />
      </span>
    </p>
  );
}

/** Avatar discret de l'assistant (pictogramme neutre, pas de personnage). */
function TutorAvatar() {
  return (
    <span
      aria-hidden="true"
      className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-brand text-white"
    >
      <GraduationCap className="h-4 w-4" strokeWidth={1.75} />
    </span>
  );
}

/**
 * Un tour de conversation. `streaming` : le tour est encore en cours
 * (POST /api/chat/stream) — état explicite pendant le retrieval (« Le tuteur
 * recherche dans le cours… », jamais un spinner vague), puis tokens au fur et
 * à mesure, rendus en Markdown avec curseur attaché au dernier bloc
 * (cf. .streaming-md dans globals.css).
 *
 * Le rendu Markdown repasse à chaque token : le contenu reste petit (quelques
 * Ko), le reparsing est négligeable face à la latence réseau/Ollama.
 */
export default function ChatMessage({
  message,
  streaming = false,
}: {
  message: Message;
  streaming?: boolean;
}) {
  const isUser = message.role === "user";
  const reducedMotion = useReducedMotion();
  const awaitingFirstToken = streaming && !message.content;

  // Apparition : fade + léger slide-up 200 ms (désactivé si reduced motion).
  const appear = reducedMotion
    ? {}
    : {
        initial: { opacity: 0, y: 8 },
        animate: { opacity: 1, y: 0 },
        transition: { duration: 0.2, ease: "easeOut" as const },
      };

  if (isUser) {
    return (
      <motion.div {...appear} className="flex justify-end">
        <div className="max-w-[85%] rounded-lg border border-brand-border bg-brand-soft px-4 py-3">
          <p className="whitespace-pre-wrap break-words leading-relaxed">
            {message.content}
          </p>
        </div>
      </motion.div>
    );
  }

  return (
    <motion.div {...appear} className="flex items-start gap-3">
      <TutorAvatar />
      <div
        className={`min-w-0 flex-1 rounded-lg border px-4 py-3 ${
          message.refused
            ? "border-warn-border bg-warn-soft"
            : "border-border-soft bg-surface shadow-sm"
        }`}
      >
        {/* aria-live : la réponse en cours de streaming est annoncée poliment. */}
        <div aria-live={streaming ? "polite" : undefined}>
          <p className="sr-only">Réponse du tuteur</p>

          {awaitingFirstToken ? (
            <SearchingDots />
          ) : (
            <div
              className={`tutor-md break-words text-ink ${
                streaming ? "streaming-md" : ""
              }`}
            >
              <ReactMarkdown>{message.content}</ReactMarkdown>
            </div>
          )}
        </div>

        {message.refused && <RefusalBadge />}

        {!message.refused && message.sources && (
          <SourceList sources={message.sources} />
        )}

        {!streaming && message.latencyMs != null && (
          <p className="mt-2 text-[11px] text-ink-muted/70">
            Réponse générée en {(message.latencyMs / 1000).toFixed(1)} s
          </p>
        )}
      </div>
    </motion.div>
  );
}
