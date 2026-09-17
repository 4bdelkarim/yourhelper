/**
 * Fil contextuel (façon fil d'Ariane) en haut de la zone de chat :
 * rappelle le corpus et le sujet de la session. Discret mais fonctionnel :
 * dans une session d'apprentissage, on sait toujours où on en est.
 * Le sujet est dérivé de la première question de la conversation (réel,
 * jamais inventé) — tronqué raisonnablement.
 */
export default function Breadcrumb({ topic }: { topic?: string }) {
  return (
    <nav
      aria-label="Contexte de la discussion"
      className="flex items-center gap-1.5 text-xs text-slate-500"
    >
      <span className="font-medium text-univ-700">Corpus de cours ML</span>
      {topic && (
        <>
          <span aria-hidden="true" className="text-slate-300">
            /
          </span>
          <span className="max-w-[60ch] truncate" title={topic}>
            {topic}
          </span>
        </>
      )}
    </nav>
  );
}
