import { api } from "./api";
import type { DailyQuote } from "./types";

/** Shown if the quote request fails outright. The message area is never blank
 * (DECISIONS.md 10) -- the server has its own copy of this rule and its own
 * fallback; this one covers the case where nobody answered at all. */
export const FALLBACK_QUOTE_TEXT = "Every page you read is one you didn't have before.";

export const FALLBACK_QUOTE: DailyQuote = {
  text: FALLBACK_QUOTE_TEXT,
  attribution: null,
};

/** Today's quote. Never throws, never resolves to an empty string.
 *
 * Which quote it is comes from the server, which derives it from the day key.
 * Nothing here shuffles, samples, or remembers -- reloading the page cannot
 * change the quote because the client never chooses it.
 *
 * An empty or whitespace-only attribution is normalized to null on the way in,
 * so the renderer has exactly one thing to test for. The server already does
 * this (10.1, amended); doing it again here means a hand-edited response, or a
 * server from a different build, still cannot produce a stray em dash. */
export async function fetchQuote(): Promise<DailyQuote> {
  try {
    const { text, attribution } = await api.quote();
    const words = text?.trim();
    if (!words) return FALLBACK_QUOTE;
    return { text: words, attribution: attribution?.trim() || null };
  } catch {
    return FALLBACK_QUOTE;
  }
}
