import type { Source } from "@/lib/api";
import SourceList from "./SourceList";

export interface Message {
  role: "user" | "assistant";
  content: string;
  refused?: boolean;
  sources?: Source[];
  latencyMs?: number;
}

/**
 * `streaming` : le tour est encore en cours (POST /api/chat/stream) —
 * affiche un curseur clignotant tant qu'aucun token n'est arrivé (phase
 * retrieval : les sources n'ont pas encore été reçues), puis les tokens
 * au fur et à mesure avec un curseur en fin de texte.
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
        className={`max-w-[85%] rounded-2xl px-4 py-3 ${
          isUser
            ? "bg-blue-600 text-white"
            : message.refused
              ? "border border-amber-300 bg-amber-50 text-amber-900"
              : "bg-white text-slate-900 shadow-sm"
        }`}
      >
        {!isUser && (
          <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-400">
            {message.refused ? "Tuteur — refus" : "Tuteur"}
          </p>
        )}
        {awaitingFirstToken ? (
          <p className="text-sm text-slate-500">
            Recherche dans le corpus…
            <span className="ml-1 text-xs text-slate-400">
              (reformulation + retrieval + reranker, 15 à 30 s)
            </span>
            <span className="ml-1 inline-block h-3 w-1.5 animate-pulse bg-slate-400 align-middle" />
          </p>
        ) : (
          <p className="whitespace-pre-wrap leading-relaxed">
            {message.content}
            {streaming && (
              <span className="ml-0.5 inline-block h-3.5 w-1.5 animate-pulse bg-slate-400 align-middle" />
            )}
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
