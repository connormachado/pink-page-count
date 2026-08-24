type Props = {
  message: string | null;
};

/** A warm line that appears under the number after a save and then leaves.
 *
 * Non-blocking by construction: no modal, no dismiss button, nothing to click.
 * It fades out on its own; App clears it a moment later.
 *
 * The outer element never remounts, because a live region that comes and goes
 * is a live region screen readers miss. The inner span is keyed on the message
 * so a second save restarts the fade instead of inheriting a finished one.
 * With reduced motion the fade is not applied at all -- the words still appear.
 */
export function SaveConfirmation({ message }: Props) {
  return (
    <p role="status" aria-live="polite" className="h-5 text-center text-sm text-[var(--rose-muted)]">
      {message ? (
        <span key={message} className="motion-safe:animate-[fade-away_var(--dur-confirm)_ease-out_forwards]">
          {message}
        </span>
      ) : null}
    </p>
  );
}
