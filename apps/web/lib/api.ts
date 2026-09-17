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

/** Charge de l'event SSE `meta` — reflète EXACTEMENT _meta_payload côté backend. */
export interface StreamMeta {
  conversation_id: string;
  refused: boolean;
  sources: Source[];
  rewritten_query: string;
  sub_queries: string[];
}

export interface ChatStreamHandlers {
  onMeta?: (meta: StreamMeta) => void;
  onToken?: (delta: string) => void;
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

/**
 * Appelle POST /api/chat/stream (SSE) — même request body que sendChat.
 *
 * Contrat de flux backend (apps/api/sse.py) :
 *   event: meta   data: {conversation_id, refused, sources, rewritten_query, sub_queries}
 *   event: token  data: {delta}
 *   event: done   data: {latency_ms}
 *   event: error  data: {code, message, status}
 *
 * Comportement d'erreur aligné sur le backend :
 *   - erreur AVANT l'ouverture du flux (retrieval, index, validation) → le
 *     serveur répond 5xx/422 classique → ApiError (comme sendChat) ;
 *   - erreur PENDANT le flux (tokens déjà affichés) → event `error` → ApiError.
 *
 * Résout avec la latence totale (`done`) une fois le flux terminé.
 */
export async function sendChatStream(
  params: {
    message: string;
    conversationId: string;
    history: HistoryTurn[];
    k?: number;
  },
  handlers: ChatStreamHandlers = {},
): Promise<{ latencyMs?: number }> {
  let resp: Response;
  try {
    resp = await fetch(`${API_URL}/api/chat/stream`, {
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
    throw new ApiError(
      "network_error",
      "Impossible de joindre le serveur. Vérifiez que l'API tourne sur " + API_URL,
      0,
    );
  }

  // Le backend n'ouvre le flux qu'après la phase bloquante : toute réponse
  // non-2xx ici est une erreur REST classique, jamais un flux partiel.
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

  if (!resp.body) {
    throw new ApiError("stream_unavailable", "Flux indisponible (réponse sans corps).", resp.status);
  }

  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let latencyMs: number | undefined;

  function handleEvent(event: string, dataRaw: string) {
    let data: unknown;
    try {
      data = JSON.parse(dataRaw);
    } catch {
      return; // charge malformée : on ignore l'event plutôt que de casser le flux
    }
    if (event === "meta") {
      handlers.onMeta?.(data as StreamMeta);
    } else if (event === "token") {
      handlers.onToken?.((data as { delta: string }).delta);
    } else if (event === "done") {
      latencyMs = (data as { latency_ms?: number }).latency_ms;
    } else if (event === "error") {
      const e = data as { code?: string; message?: string; status?: number };
      throw new ApiError(
        e.code ?? "stream_error",
        e.message ?? "Erreur pendant la génération.",
        e.status ?? 500,
      );
    }
    // event inconnu : ignoré silencieusement (tolérant aux évolutions du contrat)
  }

  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      // Découpage incrémental : les événements SSE sont séparés par une ligne
      // vide (\n\n). Le reste incomplet reste dans le buffer.
      let sep: number;
      while ((sep = buffer.indexOf("\n\n")) !== -1) {
        const block = buffer.slice(0, sep);
        buffer = buffer.slice(sep + 2);
        let event = "message";
        const dataLines: string[] = [];
        for (const line of block.split("\n")) {
          if (line.startsWith("event:")) event = line.slice(6).trim();
          else if (line.startsWith("data:")) dataLines.push(line.slice(5).replace(/^ /, ""));
        }
        if (dataLines.length) handleEvent(event, dataLines.join("\n"));
      }
    }
  } catch (err) {
    // Fermer proprement la connexion côté client (erreur réseau en cours de flux
    // ou ApiError levée depuis handleEvent) — les tokens déjà affichés restent.
    await reader.cancel().catch(() => {});
    if (err instanceof ApiError) throw err;
    throw new ApiError(
      "stream_interrupted",
      "Le flux a été interrompu pendant la génération.",
      0,
    );
  }

  return { latencyMs };
}
