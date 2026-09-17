"use client";

import { useEffect } from "react";

export interface Conversation {
  id: string;
  title: string;
}

/**
 * Sidebar gauche fixe — historique des conversations, style institutionnel
 * épuré (liste simple, pas de cartes). Sur mobile : tiroir coulissant avec
 * overlay, fermé par défaut (le bouton hamburger vit dans page.tsx).
 *
 * Persistance : aucune (prototype) — l'historique de session vit dans
 * l'état React de page.tsx et disparaît au rechargement, comme le fil.
 */
export default function ConversationSidebar({
  conversations,
  activeId,
  onSelect,
  onNew,
  open = false,
  onClose,
}: {
  conversations: Conversation[];
  activeId: string;
  onSelect: (id: string) => void;
  onNew: () => void;
  open?: boolean;
  onClose: () => void;
}) {
  // Échap ferme le tiroir mobile (accessibilité clavier).
  useEffect(() => {
    if (!open) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [open, onClose]);

  const list = (
    <>
      <button
        onClick={onNew}
        className="mb-4 w-full rounded-md bg-univ-700 px-3 py-2.5 text-sm font-medium text-white hover:bg-univ-600"
      >
        + Nouvelle conversation
      </button>

      {conversations.length === 0 ? (
        <p className="px-1 text-sm text-slate-400">
          Aucune conversation pour le moment.
        </p>
      ) : (
        <nav aria-label="Historique des conversations">
          <p className="mb-2 px-1 text-xs font-semibold uppercase tracking-wide text-slate-500">
            Historique
          </p>
          <ul className="space-y-0.5">
            {conversations.map((c) => (
              <li key={c.id}>
                <button
                  onClick={() => onSelect(c.id)}
                  aria-current={c.id === activeId ? "page" : undefined}
                  className={`w-full truncate rounded-md px-3 py-2 text-left text-sm ${
                    c.id === activeId
                      ? "bg-univ-100 font-medium text-univ-800"
                      : "text-slate-600 hover:bg-slate-100"
                  }`}
                  title={c.title}
                >
                  {c.title}
                </button>
              </li>
            ))}
          </ul>
        </nav>
      )}
    </>
  );

  return (
    <>
      {/* Desktop : colonne fixe */}
      <aside className="hidden w-64 shrink-0 flex-col border-r border-slate-200 bg-white px-3 py-4 md:flex">
        {list}
      </aside>

      {/* Mobile : tiroir coulissant + overlay */}
      {open && (
        <div className="fixed inset-0 z-40 md:hidden" role="dialog" aria-modal="true">
          <button
            aria-label="Fermer le menu"
            onClick={onClose}
            className="absolute inset-0 bg-slate-900/40"
          />
          <aside className="absolute inset-y-0 left-0 flex w-72 flex-col bg-white px-3 py-4 shadow-xl">
            {list}
          </aside>
        </div>
      )}
    </>
  );
}
