import { useEffect, useRef } from "react";
import { prefersReducedMotion } from "../motion";

type Props = {
  /** The threshold just crossed, or null. Never a distance to one. */
  milestone: number | null;
};

const PARTICLES = 90;
const RUN_MS = 2400;
const GRAVITY = 0.00035;

/** Hand-rolled canvas confetti. No library, no remote asset, ~60 lines of loop.
 *
 * DECISIONS.md 8: this celebrates an arrival and says nothing about a distance.
 * The component is handed a number she has already reached and has no way to
 * learn what the next one is.
 *
 * With prefers-reduced-motion the message still appears and no canvas is ever
 * created. The loop also stops the moment the tab is hidden -- she reads on
 * battery in a library.
 */
export function Celebration({ milestone }: Props) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const reduced = prefersReducedMotion();

  useEffect(() => {
    if (milestone === null || prefersReducedMotion()) return;
    const canvas = canvasRef.current;
    const context = canvas?.getContext("2d");
    if (!canvas || !context) return;

    const width = (canvas.width = window.innerWidth);
    const height = (canvas.height = window.innerHeight);

    // Colors come off the document, so tokens.css stays the only place in the
    // repo where a hex literal appears (DECISIONS.md 9.1). There is deliberately
    // no hardcoded fallback color here: if the tokens cannot be read we simply
    // do not draw, and the message below carries the celebration on its own.
    const styles = getComputedStyle(document.documentElement);
    const palette = ["--pink-hot", "--pink-edge", "--pink-surface", "--rose-muted"]
      .map((token) => styles.getPropertyValue(token).trim())
      .filter(Boolean);
    if (palette.length === 0) return;

    const particles = Array.from({ length: PARTICLES }, () => ({
      x: width * (0.3 + Math.random() * 0.4),
      y: height * 0.34,
      vx: (Math.random() - 0.5) * 0.5,
      vy: -(0.25 + Math.random() * 0.45),
      spin: (Math.random() - 0.5) * 0.25,
      angle: Math.random() * Math.PI,
      size: 5 + Math.random() * 7,
      color: palette[Math.floor(Math.random() * palette.length)],
    }));

    let frame: number | null = null;
    let last = performance.now();
    let elapsed = 0;

    const stop = () => {
      if (frame !== null) cancelAnimationFrame(frame);
      frame = null;
      context.clearRect(0, 0, width, height);
    };

    const draw = (now: number) => {
      const dt = Math.min(now - last, 48);
      last = now;
      elapsed += dt;
      context.clearRect(0, 0, width, height);
      context.globalAlpha = Math.max(0, 1 - elapsed / RUN_MS);

      for (const p of particles) {
        p.vy += GRAVITY * dt;
        p.x += p.vx * dt;
        p.y += p.vy * dt;
        p.angle += p.spin * (dt / 16);
        context.save();
        context.translate(p.x, p.y);
        context.rotate(p.angle);
        context.fillStyle = p.color;
        context.fillRect(-p.size / 2, -p.size / 2, p.size, p.size * 0.6);
        context.restore();
      }

      if (elapsed < RUN_MS) frame = requestAnimationFrame(draw);
      else stop();
    };
    frame = requestAnimationFrame(draw);

    const onVisibilityChange = () => {
      if (document.hidden) stop();
    };
    document.addEventListener("visibilitychange", onVisibilityChange);

    return () => {
      stop();
      document.removeEventListener("visibilitychange", onVisibilityChange);
    };
  }, [milestone]);

  if (milestone === null) return null;

  return (
    <>
      <p
        data-testid="milestone"
        role="status"
        className="text-center text-[var(--ink)] motion-safe:animate-[rise-in_var(--dur-ui)_ease-out]"
      >
        {milestone.toLocaleString()} pages. Look at that.
      </p>
      {reduced ? null : (
      <canvas
        ref={canvasRef}
        aria-hidden="true"
        className="pointer-events-none fixed inset-0 z-10 h-full w-full"
      />
      )}
    </>
  );
}
