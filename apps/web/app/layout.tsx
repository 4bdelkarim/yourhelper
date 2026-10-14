import type { Metadata } from "next";
import { GraduationCap } from "lucide-react";
import { Source_Sans_3, JetBrains_Mono } from "next/font/google";
import ThemeToggle from "@/components/ThemeToggle";
import "./globals.css";

/* Polices institutionnelles : Source Sans 3 pour le texte, JetBrains Mono
 * pour le code — via next/font (auto-hébergées, zéro requête externe). */
const sourceSans = Source_Sans_3({
  subsets: ["latin"],
  variable: "--font-source-sans",
  display: "swap",
});
const jetbrains = JetBrains_Mono({
  subsets: ["latin"],
  variable: "--font-jetbrains",
  display: "swap",
});

export const metadata: Metadata = {
  title: "Tuteur Machine Learning — Université Clermont Auvergne",
  description:
    "Tuteur pédagogique RAG — réponses ancrées dans le corpus de cours de machine learning (TER ISIMA / Clermont Auvergne INP, laboratoire LIMOS).",
};

/**
 * Thème : préférence système + choix manuel persisté (localStorage), appliqué
 * AVANT la première peinture par ce script inline — aucun flash de fond.
 */
const themeInit = `(function(){try{var s=localStorage.getItem("tuteur.theme");var d=s?s==="dark":window.matchMedia("(prefers-color-scheme: dark)").matches;if(d)document.documentElement.classList.add("dark");}catch(e){}})();`;

/**
 * Squelette institutionnel inspiré de l'ENT UCA : bandeau utilitaire fin,
 * en-tête avec logo neutre (texte « Tuteur ML » + pictogramme — emplacement à
 * remplacer par le logo officiel si l'autorisation de marque est obtenue),
 * bloc contact et pied de page.
 */
export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="fr" suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: themeInit }} />
      </head>
      <body
        className={`${sourceSans.variable} ${jetbrains.variable} flex min-h-screen flex-col bg-surface font-sans text-ink antialiased`}
      >
        {/* Lien d'évitement — première tabulation (comme sur uca.fr). */}
        <a
          href="#contenu"
          className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-50 focus:bg-brand focus:px-4 focus:py-2 focus:text-white"
        >
          Aller au contenu
        </a>

        {/* Bandeau utilitaire fin — équivalent « Apps & ENT / Connexion ». */}
        <div id="haut" className="bg-brand-ink text-white">
          <div className="mx-auto flex h-8 max-w-6xl items-center justify-between px-4 text-xs">
            <p className="tracking-wide">
              Université Clermont Auvergne · ISIMA · Laboratoire LIMOS
            </p>
            <nav aria-label="Liens institutionnels" className="flex items-center gap-4">
              <a
                href="https://ent.uca.fr/"
                target="_blank"
                rel="noopener noreferrer"
                className="underline decoration-white/40 underline-offset-2 hover:decoration-white"
              >
                Retour à l&apos;ENT
              </a>
              <ThemeToggle />
            </nav>
          </div>
        </div>

        {/* En-tête : logo neutre à gauche (sans fichier image). */}
        <header className="border-b border-border-soft bg-surface">
          <div className="mx-auto flex h-16 max-w-6xl items-center gap-3 px-4">
            <span
              aria-hidden="true"
              className="flex h-10 w-10 items-center justify-center rounded-lg bg-brand text-white"
            >
              <GraduationCap className="h-6 w-6" strokeWidth={1.75} />
            </span>
            <div className="leading-tight">
              <p className="text-lg font-semibold tracking-tight text-ink">
                Tuteur ML
              </p>
              <p className="text-xs text-ink-muted">
                Tuteur pédagogique — Machine Learning
              </p>
            </div>
          </div>
        </header>

        {children}

        {/* Bloc contact institutionnel. */}
        <section className="border-t border-border-soft bg-surface-alt">
          <div className="mx-auto max-w-6xl px-4 py-6 text-sm text-ink-muted">
            <p className="font-semibold text-ink">Un problème ?</p>
            <p className="mt-1">
              Contactez le centre de service (CDS) :{" "}
              <a
                href="https://www.uca.fr/centre-de-service-cds"
                target="_blank"
                rel="noopener noreferrer"
                className="text-brand-ink underline underline-offset-2 hover:text-brand"
              >
                www.uca.fr/centre-de-service-cds
              </a>
            </p>
          </div>
        </section>

        {/* Pied de page institutionnel. */}
        <footer className="border-t border-border-soft bg-surface">
          <div className="mx-auto flex max-w-6xl flex-col gap-3 px-4 py-6 text-xs text-ink-muted md:flex-row md:items-center md:justify-between">
            <p>49 bd François Mitterrand, CS 60032, 63001 Clermont-Ferrand</p>
            <nav
              aria-label="Liens légaux"
              className="flex flex-wrap items-center gap-x-4 gap-y-2"
            >
              <a
                href="https://www.uca.fr/mentions-legales"
                target="_blank"
                rel="noopener noreferrer"
                className="underline underline-offset-2 hover:text-ink"
              >
                Mentions légales
              </a>
              <a
                href="https://www.uca.fr/accessibilite"
                target="_blank"
                rel="noopener noreferrer"
                className="underline underline-offset-2 hover:text-ink"
              >
                Accessibilité
              </a>
              <a
                href="https://www.uca.fr/plan-du-site"
                target="_blank"
                rel="noopener noreferrer"
                className="underline underline-offset-2 hover:text-ink"
              >
                Plan du site
              </a>
              <a href="#haut" className="underline underline-offset-2 hover:text-ink">
                Haut de page
              </a>
            </nav>
          </div>
        </footer>
      </body>
    </html>
  );
}
