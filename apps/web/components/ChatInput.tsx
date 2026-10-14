"use client";

import { useEffect, useRef, type FormEvent, type KeyboardEvent } from "react";
import { SendHorizontal } from "lucide-react";

/**
 * Zone de saisie : textarea auto-extensible (jusqu'à ~6 lignes), Entrée =
 * envoyer, Maj+Entrée = retour à la ligne. Désactivée pendant la génération.
 * Le parent reste maître du state (`value`/`onChange`/`onSubmit`) — aucune
 * logique de conversation ici.
 */
export default function ChatInput({
  value,
  onChange,
  onSubmit,
  disabled = false,
}: {
  value: string;
  onChange: (v: string) => void;
  onSubmit: (e: FormEvent) => void;
  disabled?: boolean;
}) {
  const ref = useRef<HTMLTextAreaElement>(null);

  // Auto-extension : hauteur recalculée au contenu, plafonnée par max-height.
  function autoResize() {
    const el = ref.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 160)}px`;
  }

  // Rétracte le textarea quand le parent vide la saisie (après envoi).
  useEffect(() => {
    autoResize();
  }, [value]);

  function handleKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      if (!disabled && value.trim()) {
        e.currentTarget.form?.requestSubmit();
      }
    }
    // Maj+Entrée : comportement natif (retour à la ligne).
  }

  return (
    <form onSubmit={onSubmit} className="flex items-end gap-2">
      <textarea
        ref={ref}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={handleKeyDown}
        rows={1}
        maxLength={2000}
        disabled={disabled}
        placeholder="Votre question…"
        aria-label="Votre question"
        className="max-h-40 flex-1 resize-none rounded-lg border border-border-soft bg-surface px-4 py-2.5 text-base leading-relaxed placeholder:text-ink-muted/70 focus-visible:border-brand focus-visible:outline-none disabled:opacity-50"
      />
      <button
        type="submit"
        disabled={disabled || !value.trim()}
        className="flex shrink-0 items-center gap-2 rounded-lg bg-brand px-5 py-2.5 font-medium text-white hover:bg-brand-hover disabled:cursor-not-allowed disabled:opacity-50"
      >
        <SendHorizontal className="h-4 w-4" strokeWidth={1.75} aria-hidden="true" />
        <span>Envoyer</span>
      </button>
    </form>
  );
}
