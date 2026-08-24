import { api } from "./api";

/** Shown if the quote request fails outright. The message area is never blank
 * (DECISIONS.md 10) -- the server has its own copy of this rule and its own
 * fallback; this one covers the case where nobody answered at all. */
export const FALLBACK_QUOTE = "Every page you read is one you didn't have before.";

/** Today's quote. Never throws, never resolves to an empty string.
 *
 * Which quote it is comes from the server, which derives it from the day key.
 * Nothing here shuffles, samples, or remembers -- reloading the page cannot
 * change the quote because the client never chooses it. */
export async function fetchQuote(): Promise<string> {
  try {
    const { quote } = await api.quote();
    return quote.trim() || FALLBACK_QUOTE;
  } catch {
    return FALLBACK_QUOTE;
  }
}
