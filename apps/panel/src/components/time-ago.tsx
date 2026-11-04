import { useEffect, useState } from "react";
import { formatDateTime, formatRelative } from "@/lib/format";

export function TimeAgo({ date }: { date: string | Date }) {
  const [, tick] = useState(0);

  useEffect(() => {
    const id = window.setInterval(() => tick((n) => n + 1), 1000);
    return () => window.clearInterval(id);
  }, []);

  return (
    <time dateTime={new Date(date).toISOString()} title={formatDateTime(date)}>
      {formatRelative(date)}
    </time>
  );
}
