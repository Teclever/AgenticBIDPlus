type Listener = () => void;

interface ServerState {
  portal: string;
  bidKey: string;
  bidId: string;
  startedAt: string;
}

// key → bidId (key = "portal:bidKey") — optimistic local state for the triggering tab
const generating = new Map<string, string>();
// server-side state — drives the banner for all other logged-in users
let serverGenerating: ServerState | null = null;
// key → error message (survives navigation within the session)
const errors = new Map<string, string>();
const listeners: Listener[] = [];

function notify() {
  listeners.forEach((l) => l());
}

export function startGenerating(key: string, bidId: string): void {
  generating.set(key, bidId);
  errors.delete(key); // clear any prior error when a new attempt starts
  notify();
}

export function stopGenerating(key: string): void {
  generating.delete(key);
  notify();
}

export function setGenerationError(key: string, message: string): void {
  errors.set(key, message);
  notify();
}

export function clearGenerationError(key: string): void {
  errors.delete(key);
  notify();
}

export function getGenerationError(key: string): string | null {
  return errors.get(key) ?? null;
}

export function isGenerating(key: string): boolean {
  return generating.has(key);
}

export function setServerGenerating(state: ServerState | null): void {
  serverGenerating = state;
  notify();
}

export function getAnyGenerating(): { bidId: string; portal: string; bidKey: string } | null {
  // Local (optimistic) takes priority — updates instantly for the triggering tab
  const first = [...generating.entries()][0];
  if (first) {
    const [key, bidId] = first;
    const colonIdx = key.indexOf(":");
    return { bidId, portal: key.slice(0, colonIdx), bidKey: key.slice(colonIdx + 1) };
  }
  // Fall back to server state — cross-user visibility for all other tabs
  if (serverGenerating) {
    return { bidId: serverGenerating.bidId, portal: serverGenerating.portal, bidKey: serverGenerating.bidKey };
  }
  return null;
}

export function getOtherGenerating(excludeKey: string): string | null {
  for (const [k, bidId] of generating) {
    if (k !== excludeKey) return bidId;
  }
  // Check server state for cross-user awareness
  if (serverGenerating) {
    const serverKey = `${serverGenerating.portal}:${serverGenerating.bidKey}`;
    if (serverKey !== excludeKey) return serverGenerating.bidId;
  }
  return null;
}

export function subscribe(listener: Listener): () => void {
  listeners.push(listener);
  return () => {
    const idx = listeners.indexOf(listener);
    if (idx !== -1) listeners.splice(idx, 1);
  };
}
