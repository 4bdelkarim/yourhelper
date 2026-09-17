import type { Source } from "@/lib/api";
import SourceList from "./SourceList";

export interface Message {
  role: "user" | "assistant";
  content: string;
  refused?: boolean;
  sources?: Source[];
  latencyMs?: number;
}

/** Curseur de streaming — clignotement net (animation CSS step, cf. globals.css). */
function Caret() {
  return (
    <span
      aria-hidden="true"
      className="caret-blink ml-0.5 inline-block h-4 w-[2px] bg-univ-700 align-middle"
    />
  );
}

/**
 * `streaming` : le tour est encore en cours (POST /api/chat/stream) —
 * état explicite pendant le retrieval (« Recherche dans le corpus… », jamais
 * un spinner vague), puis tokens au fur et à mesure avec curseur.
 */
export default function ChatMessage({
  message,
  streaming = false,
}: {
  message: Message;
  streaming?: boolean;
}) {
  const isUser = message.role === "user";
  const awaitingFirstToken = streaming && !message.content;

  return (
    <div className={`flex ${isUser ? "justify-end" : "justify-start"}`}>
      <div
        className={`max-w-[85%] rounded-lg px-4 py-3 ${
          isUser
            ? "border border-univ-200 bg-univ-100 text-univ-800"
            : message.refused
              ? "border border-amber-300 bg-amber-50 text-amber-900"
              : "border border-slate-200 bg-white text-slate-800 shadow-sm"
        }`}
      >
        {!isUser && (
          <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500">
            {message.refused ? "Tuteur — refus" : "Tuteur"}
          </p>
        )}

        {awaitingFirstToken ? (
          <p className="text-sm text-slate-600">
            Recherche dans le corpus…
            <span className="ml-1 text-xs text-slate-400">
              (reformulation + retrieval + reranker, 15 à 30 s)
            </span>{" "}
            <Caret />
          </p>
        ) : (
          <p className="whitespace-pre-wrap leading-relaxed">
            {message.content}
            {streaming && <Caret />}
          </p>
        )}

        {message.refused && (
          <p className="mt-2 text-xs text-amber-700">
            Le tuteur ne dispose pas d&apos;informations suffisantes dans son
            corpus de cours pour répondre à cette question.
          </p>
        )}

        {!isUser && !message.refused && message.sources && (
          <SourceList sources={message.sources} />
        )}

        {!isUser && !streaming && message.latencyMs != null && (
          <p className="mt-2 text-[11px] text-slate-400">
            {(message.latencyMs / 1000).toFixed(1)} s
          </p>
        )}
      </div>
    </div>
  );
}
