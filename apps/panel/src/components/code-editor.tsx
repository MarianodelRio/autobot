import { lazy, Suspense } from "react";
import { Skeleton } from "@/components/ui/skeleton";
import type { CodeEditorLanguage } from "./code-editor-inner";

// Lazily loaded: CodeMirror is only needed on the config editor and
// the SQL console, not on every other screen.
const CodeEditorInner = lazy(() => import("./code-editor-inner"));

export function CodeEditor(props: {
  value: string;
  onChange?: (value: string) => void;
  language: CodeEditorLanguage;
  readOnly?: boolean;
  sqlSchema?: Record<string, string[]>;
  onRun?: () => void;
}) {
  return (
    <Suspense fallback={<Skeleton className="h-40 w-full" />}>
      <CodeEditorInner {...props} />
    </Suspense>
  );
}
