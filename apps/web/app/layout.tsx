import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Tuteur Intelligent",
  description: "Tuteur pédagogique RAG — prototype",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="fr">
      <body className="bg-slate-100 text-slate-900 antialiased">{children}</body>
    </html>
  );
}
