import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Tuteur Intelligent",
  description:
    "Tuteur pédagogique RAG — réponses ancrées dans le corpus de cours de machine learning",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="fr">
      <body className="bg-paper font-sans text-slate-800 antialiased">
        {children}
      </body>
    </html>
  );
}
