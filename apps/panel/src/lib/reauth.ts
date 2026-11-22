// The step-up prompt is a tiny store: the API client asks for a fresh TOTP code (it
// cannot render anything), and the `ReauthDialog` mounted in the app shell answers.
// Kept free of imports so the client can use it without a cycle.

type Prompt = (settle: (ok: boolean) => void) => void;

let prompt: Prompt | null = null;
let inFlight: Promise<boolean> | null = null;

/** The dialog registers itself here; returns the cleanup. */
export function setReauthPrompt(next: Prompt | null): () => void {
  prompt = next;
  return () => {
    if (prompt === next) prompt = null;
  };
}

/** Resolves true once the person has passed the step-up, false if they cancel or no
 * dialog is mounted. Concurrent calls share one prompt. */
export function requestReauth(): Promise<boolean> {
  if (prompt === null) return Promise.resolve(false);
  if (inFlight === null) {
    const open = prompt;
    inFlight = new Promise<boolean>((resolve) => open(resolve)).finally(() => {
      inFlight = null;
    });
  }
  return inFlight;
}
