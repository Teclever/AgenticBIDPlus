type Listener = () => void;

// key → bidId (key = "portal:bidKey")
const generating = new Map<string, string>();
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

export function getAnyGenerating(): { bidId: string } | null {
  const entry = [...generating.values()][0];
  return entry ? { bidId: entry } : null;
}

export function getOtherGenerating(excludeKey: string): string | null {
  for (const [k, bidId] of generating) {
    if (k !== excludeKey) return bidId;
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
