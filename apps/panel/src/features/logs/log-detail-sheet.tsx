import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { formatDateTime } from "@/lib/format";

function field(item: Record<string, unknown>, ...keys: string[]): string {
  for (const key of keys) {
    const value = item[key];
    if (typeof value === "string" && value) return value;
  }
  return "";
}

export function LogDetailSheet({
  item,
  onOpenChange,
}: {
  item: Record<string, unknown> | null;
  onOpenChange: (open: boolean) => void;
}) {
  const eventId = item ? field(item, "event_id") : "";
  return (
    <Sheet open={item !== null} onOpenChange={onOpenChange}>
      <SheetContent className="w-full overflow-y-auto sm:max-w-2xl">
        {item && (
          <>
            <SheetHeader>
              <SheetTitle>{field(item, "level") || "—"}</SheetTitle>
              <SheetDescription>
                {formatDateTime(
                  field(item, "_time", "ts") || new Date().toISOString(),
                )}{" "}
                · {field(item, "service") || "—"}
                {field(item, "tenant") && ` · ${field(item, "tenant")}`}
              </SheetDescription>
            </SheetHeader>
            <div className="space-y-3 px-4 pb-4 text-sm">
              <p>{field(item, "_msg", "msg")}</p>
              {field(item, "exception") && (
                <pre className="overflow-auto whitespace-pre-wrap text-destructive">
                  {field(item, "exception")}
                </pre>
              )}
              <details>
                <summary className="cursor-pointer text-muted-foreground">
                  Resto de campos
                </summary>
                <pre className="mt-2 overflow-auto rounded-md border p-2">
                  {JSON.stringify(item, null, 2)}
                </pre>
              </details>
              {eventId && (
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => {
                    void navigator.clipboard?.writeText(eventId);
                    toast.success("event_id copiado.");
                  }}
                >
                  Copiar event_id
                </Button>
              )}
            </div>
          </>
        )}
      </SheetContent>
    </Sheet>
  );
}
