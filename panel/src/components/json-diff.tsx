import * as jsondiffpatch from "jsondiffpatch";

const differ = jsondiffpatch.create();

/** A minimal, dependency-light diff view: the raw delta, pretty-printed. A visual
 * (added/removed/moved) renderer can replace this once T27 needs one. */
export function JsonDiff({
  before,
  after,
}: {
  before: unknown;
  after: unknown;
}) {
  const delta = differ.diff(before, after);
  if (delta === undefined) {
    return <p className="text-sm text-muted-foreground">Sin cambios.</p>;
  }
  return (
    <pre className="overflow-auto rounded-md border border-border bg-muted p-3 font-mono text-xs">
      {JSON.stringify(delta, null, 2)}
    </pre>
  );
}
