"use client";

import { useEffect, useState } from "react";
import { Moon, Sun } from "lucide-react";

/**
 * Bascule clair/sombre — composant client.
 * L'état initial est posé AVANT peinture par le script inline de layout.tsx
 * (préférence système + choix manuel persisté « tuteur.theme ») ; ce bouton
 * se contente de basculer la classe .dark et de persister le choix.
 */
export default function ThemeToggle() {
  const [dark, setDark] = useState(false);

  // Synchronise l'icône avec l'état réel du document après montage.
  useEffect(() => {
    setDark(document.documentElement.classList.contains("dark"));
  }, []);

  function toggle() {
    const next = !dark;
    setDark(next);
    document.documentElement.classList.toggle("dark", next);
    try {
      localStorage.setItem("tuteur.theme", next ? "dark" : "light");
    } catch {
      /* stockage indisponible : le choix reste valable pour la session */
    }
  }

  return (
    <button
      onClick={toggle}
      aria-label={dark ? "Activer le thème clair" : "Activer le thème sombre"}
      className="rounded p-1 hover:bg-white/15"
    >
      {dark ? (
        <Sun className="h-4 w-4" strokeWidth={1.75} />
      ) : (
        <Moon className="h-4 w-4" strokeWidth={1.75} />
      )}
    </button>
  );
}
