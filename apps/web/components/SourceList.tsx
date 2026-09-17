import type { Source } from "@/lib/api";

/**
 * Affiche les sources RÉELLES renvoyées par le retrieval.
 * Le libellé (`label`) est celui produit par citation_label() côté backend :
 *   web : "web · d2l.ai · « titre » · §section"
 *   pdf : "pdf · 05_RNN.pdf · §3.1- LSTM"
 * Un lien n'est affiché QUE si source_url existe réellement (jamais inventé).
 */
export default function SourceList({ sources }: { sources: Source[] }) {
  if (!sources.length) return null;

  return (
    <div className="mt-3 border-t border-slate-200 pt-2">
      <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">
        Sources
      </p>
      <ul className="mt-1 space-y-1">
        {sources.map((s, i) => (
          <li key={i} className="text-sm leading-snug text-slate-600">
            <span className="mr-1 text-slate-400" aria-hidden="true">
              •
            </span>
            {s.source_url ? (
              <a
                href={s.source_url}
                target="_blank"
                rel="noopener noreferrer"
                className="text-univ-700 underline decoration-dotted underline-offset-2 hover:text-univ-600"
              >
                {s.label}
              </a>
            ) : (
              <span>{s.label}</span>
            )}
            {s.source_type === "pdf" && s.page_start != null && (
              <span className="ml-1 text-slate-400">
                (p.{s.page_start}
                {s.page_end != null && s.page_end !== s.page_start
                  ? `–${s.page_end}`
                  : ""}
                )
              </span>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}
