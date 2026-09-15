/**
 * Client API typé — contrat IDENTIQUE au backend FastAPI (apps/api/schemas/chat.py).
 * Aucun champ inventé : reflète exactement ce que le backend renvoie.
 */

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export const REFUSAL_MESSAGE =
  "Les documents fournis ne permettent pas de répondre à cette question.";

export interface HistoryTurn {
  role: "user" | "assistant";
  content: string;
}

export interface Source {
  label: string;
  source: string;
  source_type: string | null;
  source_url: string | null;
  title: string | null;
  source_id: string | null;
  section: string | null;
  page_start: number | null;
  page_end: number | null;
  score: number | null;
}

export interface ChatResponse {
  conversation_id: string;
  answer: string;
  refused: boolean;
  sources: Source[];
  meta: {
    rewritten_query?: string;
    sub_queries?: string[];
    latency_ms?: number;
  };
}

export class ApiError extends Error {
  code: string;
  status: number;

  constructor(code: string, message: string, status: number) {
    super(message);
    this.code = code;
    this.status = status;
  }
}

/**
 * Appelle POST /api/chat. `history` contient les tours PRÉCÉDENTS uniquement
 * (le message courant est transmis via `message`) — c'est le contrat du backend.
 */
export async function sendChat(params: {
  message: string;
  conversationId: string;
  history: HistoryTurn[];
  k?: number;
}): Promise<ChatResponse> {
  let resp: Response;
  try {
    resp = await fetch(`${API_URL}/api/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        message: params.message,
        conversation_id: params.conversationId,
        history: params.history,
        ...(params.k ? { k: params.k } : {}),
      }),
      cache: "no-store",
    });
  } catch {
    // Échec réseau / CORS / backend injoignable
    throw new ApiError(
      "network_error",
      "Impossible de joindre le serveur. Vérifiez que l'API tourne sur " + API_URL,
      0,
    );
  }

  if (!resp.ok) {
    let code = "http_error";
    let message = `Erreur serveur (HTTP ${resp.status})`;
    try {
      const body = await resp.json();
      if (body?.detail?.code) code = body.detail.code;
      if (body?.detail?.message) message = body.detail.message;
      else if (typeof body?.detail === "string") message = body.detail;
    } catch {
      /* réponse non-JSON : on garde le message générique */
    }
    throw new ApiError(code, message, resp.status);
  }

  return resp.json();
}
