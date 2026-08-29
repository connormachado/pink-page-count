import type {
  Class,
  ClassCreate,
  ClassPatch,
  DailyQuote,
  Entry,
  EntryCreate,
  EntryPatch,
  Settings,
  SettingsPatch,
  Stats,
} from "./types";

/** The server said no, and told us why in {"error": "..."} (DECISIONS.md 4.2).
 * The message is written for a person; show it verbatim. */
export class ApiError extends Error {}

/** We never reached the server at all -- `fetch` itself rejected, so there was
 * no response, no status, and nobody on the other end. Different from ApiError:
 * there is no message from anyone, and there is no data -- so the UI must say
 * the app is not running rather than render a zero that looks like a real
 * total. This is the ONLY error that may say the app is not running. */
export class ServerUnreachable extends Error {
  constructor() {
    super("Can't reach the reading tracker.");
  }
}

/** The server answered, and its answer was that it had failed -- a 5xx. It is
 * running; something inside it, or under it, did not work. That is a different
 * state from ServerUnreachable and it used to render the same wrong message:
 * a failed write came back as a body-less 500, was read as "nobody answered",
 * and the app told her it was closed while it was answering (AUDIT.md B4,
 * DECISIONS.md 4.5).
 *
 * Extends ApiError on purpose. Every call site already routes an ApiError to
 * the message slot beside the thing she was doing, and that is exactly where a
 * failed save belongs -- next to the form, with her typing still in it, not
 * over the whole page. Handling it separately is a choice each caller makes
 * (App does, for the load path); ignoring the distinction still does the right
 * thing. */
export class ServerFault extends ApiError {}

const FALLBACK = "That didn't save. Try once more?";

/** What a 5xx says when it carried no message of its own -- a crash before any
 * handler ran, or a dev proxy answering for a backend that is gone. It has to
 * be true without knowing the cause: the save did not happen, the app is not
 * being called closed, and nothing blames her (DECISIONS.md 4.5, 8). */
const SERVER_FAULT_FALLBACK =
  "That didn't save — something went wrong inside the app. " +
  "Everything you logged before is still there.";

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
    // A 5xx is the server answering, whatever came back in the body. Something
    // reached us and told us it failed, which is not the same as nothing
    // reaching us at all -- only a rejected fetch (above) means that. A 5xx
    // with no JSON body used to be turned into ServerUnreachable here, and
    // that one line is what made a failed save render as "the app isn't
    // running" (AUDIT.md B4).
    if (response.status >= 500) throw new ServerFault(message ?? SERVER_FAULT_FALLBACK);
    throw new ApiError(message ?? FALLBACK);
  }

  return body as T;
}

export const api = {
  stats: () => request<Stats>("/api/stats"),
  quote: () => request<DailyQuote>("/api/quote"),
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

  /** "This page is still open." The frozen app quits when these stop arriving,
   * which is what makes closing the tab quit the app (DECISIONS.md 16.2). No
   * body, no response, and nothing on the server touches a data file. */
  heartbeat: () => request<void>("/api/heartbeat", { method: "POST" }),

  settings: () => request<Settings>("/api/settings"),
  updateSettings: (changes: SettingsPatch) =>
    request<Settings>("/api/settings", { method: "PATCH", body: JSON.stringify(changes) }),
};
