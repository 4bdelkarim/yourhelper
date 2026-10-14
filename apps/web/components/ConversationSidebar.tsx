"use client";

import { useEffect } from "react";
import { PanelLeftClose, PanelLeftOpen, Trash2 } from "lucide-react";

export interface Conversation {
  id: string;
  title: string;
}

/**
 * Sidebar gauche — historique des conversations, style institutionnel épuré.
 *
 * Desktop : colonne fixe repliable ENTièrement (comme ChatGPT/Claude) via le
 * bouton pivot en haut ; repliée, elle libère toute la largeur pour le chat.
 * Mobile : tiroir coulissant avec overlay, fermé par défaut (le bouton
 * hamburger vit dans page.tsx).
 *
 * Chaque conversation peut être supprimée (corbeille, avec confirmation —
 * la suppression est définitive, l'historique vit dans le localStorage).
 */
export default function ConversationSidebar({
  conversations,
  activeId,
  onSelect,
  onNew,
  onDelete,
  open = false,
  onClose,
  collapsed = false,
  onToggleCollapsed,
}: {
  conversations: Conversation[];
  activeId: string;
  onSelect: (id: string) => void;
  onNew: () => void;
  onDelete: (id: string) => void;
  open?: boolean;
  onClose: () => void;
  collapsed?: boolean;
  onToggleCollapsed?: () => void;
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

  function handleDelete(e: React.MouseEvent, id: string, title: string) {
    e.stopPropagation(); // ne sélectionne pas la conversation supprimée
    if (window.confirm(`Supprimer définitivement « ${title} » ?`)) {
      onDelete(id);
    }
  }

  const list = (
    <>
      <button
        onClick={onNew}
        className="mb-4 w-full rounded-lg bg-brand px-3 py-2.5 text-sm font-medium text-white hover:bg-brand-hover"
      >
        + Nouvelle conversation
      </button>

      {conversations.length === 0 ? (
        <p className="px-1 text-sm text-ink-muted/70">
          Aucune conversation pour le moment.
        </p>
      ) : (
        <nav aria-label="Historique des conversations">
          <p className="mb-2 px-1 text-xs font-semibold uppercase tracking-wide text-ink-muted">
            Historique
          </p>
          <ul className="space-y-0.5">
            {conversations.map((c) => (
              <li key={c.id} className="group relative">
                <button
                  onClick={() => onSelect(c.id)}
                  aria-current={c.id === activeId ? "page" : undefined}
                  className={`w-full truncate rounded-lg py-2 pl-3 text-left text-sm group-hover:pr-9 ${
                    c.id === activeId
                      ? "bg-brand-soft font-medium text-brand-ink"
                      : "text-ink-muted hover:bg-surface-alt hover:text-ink"
                  }`}
                  title={c.title}
                >
                  {c.title}
                </button>
                {/* Corbeille : visible au survol/clavier (desktop), toujours
                    visible sur tactile (pas de hover). */}
                <button
                  onClick={(e) => handleDelete(e, c.id, c.title)}
                  aria-label={`Supprimer la conversation « ${c.title} »`}
                  title="Supprimer"
                  className="absolute right-1.5 top-1/2 -translate-y-1/2 rounded-md p-1.5 text-ink-muted opacity-70 hover:bg-danger-soft hover:text-danger-text focus-visible:opacity-100 md:opacity-0 md:group-hover:opacity-100 md:group-focus-within:opacity-100"
                >
                  <Trash2 className="h-3.5 w-3.5" strokeWidth={1.75} />
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
      {/* Desktop : colonne repliable entièrement. Le contenu est écrêté
          (overflow-hidden) pendant la transition ; le bouton pivot reste
          accessible même replié (position absolue dans le wrapper). */}
      <div
        className={`relative hidden shrink-0 transition-[width] duration-200 md:block ${
          collapsed ? "w-0" : "w-64"
        }`}
      >
        <aside
          aria-hidden={collapsed}
          className={`h-full overflow-hidden border-r border-border-soft bg-surface px-3 py-4 ${
            collapsed ? "invisible w-64" : "visible w-64"
          }`}
        >
          {list}
        </aside>
        {onToggleCollapsed && (
          <button
            onClick={onToggleCollapsed}
            aria-expanded={!collapsed}
            aria-label={collapsed ? "Afficher l'historique" : "Masquer l'historique"}
            title={collapsed ? "Afficher l'historique" : "Masquer l'historique"}
            className="absolute right-2 top-2 z-30 rounded-lg border border-border-soft bg-surface p-2 text-ink-muted shadow-sm hover:bg-surface-alt hover:text-ink"
          >
            {collapsed ? (
              <PanelLeftOpen className="h-4 w-4" strokeWidth={1.75} />
            ) : (
              <PanelLeftClose className="h-4 w-4" strokeWidth={1.75} />
            )}
          </button>
        )}
        <span className="sr-only" aria-live="polite">
          {collapsed ? "Historique masqué" : "Historique affiché"}
        </span>
      </div>

      {/* Mobile : tiroir coulissant + overlay */}
      {open && (
        <div className="fixed inset-0 z-40 md:hidden" role="dialog" aria-modal="true">
          <button
            aria-label="Fermer le menu"
            onClick={onClose}
            className="absolute inset-0 bg-ink/40"
          />
          <aside className="absolute inset-y-0 left-0 flex w-72 flex-col bg-surface px-3 py-4 shadow-xl">
            {list}
          </aside>
        </div>
      )}
    </>
  );
}
