import { describe, expect, it } from "vitest";
import { crossedMilestone } from "../milestones";

/** DECISIONS.md 11: upward, on a crossing, and nothing else. */
describe("crossedMilestone", () => {
  it("fires on the way up through a thousand", () => {
    expect(crossedMilestone(999, 1002)).toBe(1000);
  });

  it("does not fire again above a threshold already passed", () => {
    expect(crossedMilestone(1002, 1005)).toBe(null);
  });

  it("does not fire when the total is unchanged -- this is why a reload is silent", () => {
    expect(crossedMilestone(1002, 1002)).toBe(null);
    expect(crossedMilestone(0, 0)).toBe(null);
  });

  it("does not fire when a delete drops the total back below a threshold", () => {
    expect(crossedMilestone(1002, 998)).toBe(null);
    expect(crossedMilestone(1500, 100)).toBe(null);
  });

  it("celebrates the early wins", () => {
    expect(crossedMilestone(98, 100)).toBe(100);
    expect(crossedMilestone(0, 120)).toBe(100);
    expect(crossedMilestone(499, 500)).toBe(500);
    expect(crossedMilestone(0, 99)).toBe(null);
    expect(crossedMilestone(100, 499)).toBe(null);
  });

  it("celebrates the furthest arrival when several are crossed at once", () => {
    expect(crossedMilestone(0, 1200)).toBe(1000);
    expect(crossedMilestone(90, 520)).toBe(500);
    expect(crossedMilestone(1900, 3000)).toBe(3000);
  });

  it("keeps going past the first thousand, forever", () => {
    expect(crossedMilestone(1999, 2001)).toBe(2000);
    expect(crossedMilestone(11999, 12000)).toBe(12000);
  });

  it("exports nothing that could answer how far away the next one is", async () => {
    // DECISIONS.md 8: celebrate arrivals, never announce distances. The absence
    // of a nextMilestone()/remaining() export is the enforcement, so it is worth
    // a test -- adding one later should break this deliberately.
    const module = await import("../milestones");
    expect(Object.keys(module).sort()).toEqual([
      "EARLY_MILESTONES",
      "MILESTONE_EVERY",
      "crossedMilestone",
    ]);
  });
});
