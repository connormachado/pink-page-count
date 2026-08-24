/** Milestone thresholds and the one question we are willing to ask about them.
 *
 * DECISIONS.md 8 is the whole design of this module. The trap in a milestone
 * feature is progress toward the next one -- "40 pages to go" is a reprimand
 * wearing a friendly face, and a progress bar is the same reprimand with a
 * shape. So this file exports exactly one function, and that function can only
 * answer "did she just arrive somewhere?"
 *
 * There is deliberately no nextMilestone(), no remainder, no percentage. The
 * distance to the next threshold is never computed here, which is what makes it
 * unrenderable anywhere else.
 */

/** The early wins, so the first weeks have something in them. */
export const EARLY_MILESTONES = [100, 500];

/** And every thousand pages after that, forever. */
export const MILESTONE_EVERY = 1000;

/** The highest threshold crossed going from `before` to `after`, or null.
 *
 * Upward only, by construction: an edit or delete that drops the total back
 * below a threshold returns null because `after <= before` returns early. A
 * total that stays put returns null for the same reason -- which is why a page
 * reload can never re-fire a celebration.
 */
export function crossedMilestone(before: number, after: number): number | null {
  if (after <= before) return null;

  let highest: number | null = null;
  for (const threshold of EARLY_MILESTONES) {
    if (before < threshold && threshold <= after) highest = threshold;
  }

  // The largest multiple of 1,000 at or below `after`. If she jumped from 900
  // to 2,050 in one entry we celebrate 2,000, not 1,000 -- one arrival, the
  // furthest one.
  const thousand = Math.floor(after / MILESTONE_EVERY) * MILESTONE_EVERY;
  if (thousand > 0 && before < thousand) {
    highest = Math.max(highest ?? 0, thousand);
  }

  return highest;
}
