import { useSyncExternalStore } from "react";
import { formatDateTime, formatRelative } from "@/lib/format";

// One shared interval for every <TimeAgo> on screen (a table of 100 rows used to
// start 100 timers), running only while something is subscribed.
const listeners = new Set<() => void>();
let timer: number | undefined;
let now = Date.now();

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  if (timer === undefined) {
    now = Date.now();
    timer = window.setInterval(() => {
      now = Date.now();
      for (const notify of listeners) notify();
    }, 1000);
  }
  return () => {
    listeners.delete(listener);
    if (listeners.size === 0 && timer !== undefined) {
      window.clearInterval(timer);
      timer = undefined;
    }
  };
}

const getSnapshot = () => now;

export function TimeAgo({ date }: { date: string | Date }) {
  const current = useSyncExternalStore(subscribe, getSnapshot);
  return (
    <time dateTime={new Date(date).toISOString()} title={formatDateTime(date)}>
      {formatRelative(date, new Date(current))}
    </time>
  );
}
