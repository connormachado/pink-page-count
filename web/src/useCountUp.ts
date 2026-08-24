import { useEffect, useRef, useState } from "react";
import { durationToken, prefersReducedMotion } from "./motion";

/** Ease out past the target, then settle back onto it. The classic easeOutBack,
 * with a gentler constant than the usual 1.70158 -- a small overshoot reads as
 * enthusiasm, a large one reads as a bug. */
const OVERSHOOT = 0.9;

function easeOutBack(t: number): number {
  const p = t - 1;
  return 1 + (OVERSHOOT + 1) * p * p * p + OVERSHOOT * p * p;
}

/**
 * The number the primary numeral should be showing right now.
 *
 * `target` is always a value the server returned (DECISIONS.md 7.1). This hook
 * animates *toward* it and never produces one: whatever happens between frames,
 * the value it settles on is exactly the value it was handed.
 *
 * `token` changes only when a save happens. That is what separates a save (which
 * counts up) from switching a chip (which changes instantly), without the hook
 * needing to know what either of those things is.
 */
export function useCountUp(target: number, token: number): number {
  const [display, setDisplay] = useState(target);
  const displayRef = useRef(target);
  const tokenRef = useRef(token);
  const frameRef = useRef<number | null>(null);

  const setBoth = (value: number) => {
    displayRef.current = value;
    setDisplay(value);
  };

  useEffect(() => {
    const isSave = token !== tokenRef.current;
    tokenRef.current = token;

    const cancel = () => {
      if (frameRef.current !== null) cancelAnimationFrame(frameRef.current);
      frameRef.current = null;
    };

    // Not a save, motion is unwelcome, or nobody is looking: land on the exact
    // server value immediately. This is the correctness path, not a lesser one.
    if (!isSave || prefersReducedMotion() || document.hidden) {
      cancel();
      setBoth(target);
      return;
    }

    const from = displayRef.current;
    if (from === target) return;

    const duration = durationToken("--dur-count", 900);
    const started = performance.now();

    const step = (now: number) => {
      const t = Math.min(1, (now - started) / duration);
      if (t < 1) {
        setDisplay(Math.round(from + (target - from) * easeOutBack(t)));
        frameRef.current = requestAnimationFrame(step);
      } else {
        // Always ends on the server's number, never on a rounded frame of it.
        setBoth(target);
        frameRef.current = null;
      }
    };
    frameRef.current = requestAnimationFrame(step);

    const onVisibilityChange = () => {
      if (document.hidden) {
        cancel();
        setBoth(target);
      }
    };
    document.addEventListener("visibilitychange", onVisibilityChange);

    return () => {
      cancel();
      document.removeEventListener("visibilitychange", onVisibilityChange);
    };
    // setBoth is stable enough for this hook's purposes; it only touches refs
    // and a setState both of which are themselves stable.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [target, token]);

  return display;
}
