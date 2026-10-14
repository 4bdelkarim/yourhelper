import { CircleHelp } from "lucide-react";

/**
 * Encart de refus — ambre pâle, bienveillant, jamais une erreur :
 * le sujet n'est simplement pas dans les supports du cours.
 */
export default function RefusalBadge() {
  return (
    <div
      role="note"
      className="mt-2 flex items-start gap-2.5 rounded-lg border border-warn-border bg-warn-soft px-3.5 py-3 text-sm text-warn-text"
    >
      <CircleHelp className="mt-0.5 h-4 w-4 shrink-0" strokeWidth={1.75} aria-hidden="true" />
      <p>
        Ce sujet ne figure pas dans les supports du cours. Reformulez ou
        consultez votre enseignant.
      </p>
    </div>
  );
}
