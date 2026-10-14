/**
 * Fil d'Ariane institutionnel (façon uca.fr) : « Vous êtes ici : Accueil ›
 * Campus › Tuteur ML », suivi du sujet de la session s'il existe (dérivé de la
 * première question de la conversation — réel, jamais inventé, tronqué).
 */
export default function Breadcrumb({ topic }: { topic?: string }) {
  return (
    <nav aria-label="Fil d'Ariane" className="min-w-0">
      <p className="flex items-center gap-1.5 text-xs text-ink-muted">
        <span className="hidden sm:inline">Vous êtes ici :</span>
        <span>Accueil</span>
        <span aria-hidden="true" className="text-ink-muted/50">
          ›
        </span>
        <span className="hidden sm:inline">Campus</span>
        <span aria-hidden="true" className="hidden text-ink-muted/50 sm:inline">
          ›
        </span>
        <span className="font-medium text-brand-ink">Tuteur ML</span>
        {topic && (
          <>
            <span aria-hidden="true" className="text-ink-muted/50">
              ›
            </span>
            <span className="max-w-[40ch] truncate" title={topic}>
              {topic}
            </span>
          </>
        )}
      </p>
    </nav>
  );
}
