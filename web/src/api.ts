import type {
  Class,
  ClassCreate,
  ClassPatch,
  Entry,
  EntryCreate,
  EntryPatch,
  Stats,
} from "./types";

/** The server said no, and told us why in {"error": "..."} (DECISIONS.md 4.2).
 * The message is written for a person; show it verbatim. */
export class ApiError extends Error {}

/** We never reached the server at all. Different from ApiError: there is no
 * message from anyone, and there is no data -- so the UI must say the app is
 * not running rather than render a zero that looks like a real total. */
export class ServerUnreachable extends Error {
  constructor() {
    super("Can't reach the reading tracker.");
  }
}

const FALLBACK = "That didn't save. Try once more?";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(path, {
      ...init,
      headers: init?.body ? { "Content-Type": "application/json" } : undefined,
    });
  } catch {
    throw new ServerUnreachable();
  }

  if (response.status === 204) return undefined as T;

  let body: unknown = null;
  try {
    body = await response.json();
  } catch {
    body = null;
  }

  if (!response.ok) {
    const message =
      body && typeof body === "object" && typeof (body as { error?: unknown }).error === "string"
        ? (body as { error: string }).error
        : null;
    // A dead backend behind the dev proxy comes back as a 5xx with no JSON
    // body at all -- nobody answered, so treat it as unreachable.
    if (message === null && response.status >= 500) throw new ServerUnreachable();
    throw new ApiError(message ?? FALLBACK);
  }

  return body as T;
}

export const api = {
  stats: () => request<Stats>("/api/stats"),
  quote: () => request<{ quote: string }>("/api/quote"),
  entries: () => request<Entry[]>("/api/entries"),
  create: (entry: EntryCreate) =>
    request<Entry>("/api/entries", { method: "POST", body: JSON.stringify(entry) }),
  update: (id: string, changes: EntryPatch) =>
    request<Entry>(`/api/entries/${id}`, { method: "PATCH", body: JSON.stringify(changes) }),
  remove: (id: string) => request<void>(`/api/entries/${id}`, { method: "DELETE" }),

  classes: () => request<Class[]>("/api/classes"),
  createClass: (body: ClassCreate) =>
    request<Class>("/api/classes", { method: "POST", body: JSON.stringify(body) }),
  updateClass: (id: string, changes: ClassPatch) =>
    request<Class>(`/api/classes/${id}`, { method: "PATCH", body: JSON.stringify(changes) }),
  // Deletes the class only. Every entry logged under it is kept, with its
  // class_id cleared by the server (DECISIONS.md 12.3).
  removeClass: (id: string) => request<void>(`/api/classes/${id}`, { method: "DELETE" }),
};
