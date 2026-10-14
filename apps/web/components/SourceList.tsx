"use client";

import { useState } from "react";
import { BookOpen, ChevronDown, ExternalLink, Globe } from "lucide-react";
import type { Source } from "@/lib/api";

/**
 * Affiche les sources RÉELLES renvoyées par le retrieval, repliées par défaut
 * (« N sources »). Le libellé (`label`) est celui produit par citation_label()
 * côté backend :
 *   web : "web · d2l.ai · « titre » · §section"
 *   pdf : "pdf · 05_RNN.pdf · §3.1- LSTM"
 * Un lien n'est affiché QUE si source_url existe réellement (jamais inventé).
 */
export default function SourceList({ sources }: { sources: Source[] }) {
  const [open, setOpen] = useState(false);

  if (!sources.length) return null;

  return (
    <div className="mt-3 border-t border-border-soft pt-2">
      <button
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-ink-muted hover:text-ink"
      >
        <ChevronDown
          className={`h-3.5 w-3.5 transition-transform ${open ? "" : "-rotate-90"}`}
          strokeWidth={2}
          aria-hidden="true"
        />
        {sources.length} source{sources.length > 1 ? "s" : ""}
      </button>

      {open && (
        <ul className="mt-2 space-y-1.5">
          {sources.map((s, i) => (
            <li key={i}>
              <div className="flex items-start gap-2 rounded-lg border border-border-soft bg-surface-alt px-3 py-2">
                {s.source_type === "pdf" ? (
                  <BookOpen
                    className="mt-0.5 h-3.5 w-3.5 shrink-0 text-brand"
                    strokeWidth={1.75}
                    aria-hidden="true"
                  />
                ) : (
                  <Globe
                    className="mt-0.5 h-3.5 w-3.5 shrink-0 text-brand"
                    strokeWidth={1.75}
                    aria-hidden="true"
                  />
                )}
                <p className="min-w-0 flex-1 text-sm leading-snug text-ink-muted">
                  {s.source_url ? (
                    <a
                      href={s.source_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="break-words text-brand-ink underline decoration-dotted underline-offset-2 hover:text-brand"
                    >
                      {s.label}
                      <ExternalLink
                        className="ml-1 inline h-3 w-3 align-baseline"
                        strokeWidth={1.75}
                        aria-hidden="true"
                      />
                    </a>
                  ) : (
                    <span className="break-words">{s.label}</span>
                  )}
                  {s.source_type === "pdf" && s.page_start != null && (
                    <span className="ml-1 whitespace-nowrap text-ink-muted/70">
                      (p.{s.page_start}
                      {s.page_end != null && s.page_end !== s.page_start
                        ? `–${s.page_end}`
                        : ""}
                      )
                    </span>
                  )}
                </p>
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
