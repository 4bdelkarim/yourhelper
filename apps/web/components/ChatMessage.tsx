import type { Source } from "@/lib/api";
import SourceList from "./SourceList";

export interface Message {
  role: "user" | "assistant";
  content: string;
  refused?: boolean;
  sources?: Source[];
  latencyMs?: number;
}

export default function ChatMessage({ message }: { message: Message }) {
  const isUser = message.role === "user";

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
        <p className="whitespace-pre-wrap leading-relaxed">{message.content}</p>

        {message.refused && (
          <p className="mt-2 text-xs text-amber-700">
            Le tuteur ne dispose pas d&apos;informations suffisantes dans son
            corpus de cours pour répondre à cette question.
          </p>
        )}

        {!isUser && !message.refused && message.sources && (
          <SourceList sources={message.sources} />
        )}

        {!isUser && message.latencyMs != null && (
          <p className="mt-2 text-[11px] text-slate-400">
            {(message.latencyMs / 1000).toFixed(1)} s
          </p>
        )}
      </div>
    </div>
  );
}
