/** Pure helpers for editing a JSON document through several rjsf forms, one per
 * section: reading and writing dotted paths, building each section's sub-schema,
 * comparing documents and leaving untouched schema defaults out of what is saved. */

export type Json = Record<string, unknown>;
type Schema = Record<string, unknown>;

export function isPlainObject(value: unknown): value is Json {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/** Deep equality where a key holding `undefined` counts as absent and key order does
 * not matter (rjsf rebuilds objects in schema order). */
export function sameValue(a: unknown, b: unknown): boolean {
  if (a === b) return true;
  if (Array.isArray(a) || Array.isArray(b)) {
    if (!Array.isArray(a) || !Array.isArray(b) || a.length !== b.length)
      return false;
    return a.every((item, index) => sameValue(item, b[index]));
  }
  if (isPlainObject(a) && isPlainObject(b)) {
    const keys = new Set([...Object.keys(a), ...Object.keys(b)]);
    for (const key of keys) if (!sameValue(a[key], b[key])) return false;
    return true;
  }
  return false;
}

export function getPath(doc: unknown, path: string): unknown {
  let node: unknown = doc;
  for (const part of path.split(".")) {
    if (!isPlainObject(node)) return undefined;
    node = node[part];
  }
  return node;
}

/** A copy of `doc` with `value` at `path`, creating the objects on the way. */
export function setPath(doc: Json, path: string, value: unknown): Json {
  const [head = "", ...rest] = path.split(".");
  const out = { ...doc };
  if (rest.length === 0) {
    if (value === undefined) delete out[head];
    else out[head] = value;
    return out;
  }
  const child = isPlainObject(doc[head]) ? (doc[head] as Json) : {};
  out[head] = setPath(child, rest.join("."), value);
  return out;
}

/** Only the given paths of `doc`, nested as in the document. */
export function pickPaths(doc: Json, paths: string[]): Json {
  let out: Json = {};
  for (const path of paths) {
    const value = getPath(doc, path);
    if (value !== undefined) out = setPath(out, path, value);
  }
  return out;
}

/** `doc` with every one of `paths` taken from `part` (absent in `part`: removed). */
export function mergePaths(doc: Json, part: Json, paths: string[]): Json {
  let out = doc;
  for (const path of paths) out = setPath(out, path, getPath(part, path));
  return out;
}

function deref(
  node: unknown,
  defs: Record<string, Schema>,
): Schema | undefined {
  if (!isPlainObject(node)) return undefined;
  const ref = node.$ref;
  if (typeof ref !== "string") return node;
  const { $ref: _, ...siblings } = node;
  return { ...(defs[ref.replace("#/$defs/", "")] ?? {}), ...siblings };
}

/** The schema of one property path, or undefined when the document has no such
 * field (a shared section naming a field this pack lacks). */
export function schemaAt(root: Schema, path: string): Schema | undefined {
  const defs = (root.$defs ?? {}) as Record<string, Schema>;
  let node: Schema | undefined = root;
  for (const part of path.split(".")) {
    const properties = deref(node, defs)?.properties;
    if (!isPlainObject(properties) || !(part in properties)) return undefined;
    node = properties[part] as Schema;
  }
  return node;
}

/** A root schema holding only `paths` (each kept as declared, with its `$ref`s and
 * defaults), wrapped in untitled objects for the nesting. A section made of a single
 * object field loses that field's own title and description: the section header
 * already says them. */
export function sectionSchema(root: Schema, paths: string[]): Schema {
  const defs = (root.$defs ?? {}) as Record<string, Schema>;
  const out: Schema = { type: "object", properties: {}, $defs: root.$defs };
  for (const path of paths) {
    let leaf = schemaAt(root, path);
    if (!leaf) continue;
    if (paths.length === 1) {
      const resolved = deref(leaf, defs) ?? leaf;
      if (resolved.properties) {
        const { title: _t, description: _d, ...rest } = resolved;
        leaf = rest;
      }
    }
    const parts = path.split(".");
    let source: Schema | undefined = root;
    let target = out;
    for (const [index, part] of parts.entries()) {
      const sourceNode = deref(source, defs);
      const required = Array.isArray(sourceNode?.required)
        ? (sourceNode.required as string[])
        : [];
      if (required.includes(part))
        target.required = [...((target.required as string[]) ?? []), part];
      const properties = target.properties as Record<string, Schema>;
      if (index === parts.length - 1) {
        properties[part] = leaf;
      } else {
        properties[part] ??= { type: "object", properties: {} };
        target = properties[part];
        source = ((sourceNode?.properties ?? {}) as Record<string, Schema>)[
          part
        ];
      }
    }
  }
  return out;
}

/** What to save: `draft` without the schema defaults rjsf filled in and the person
 * left as they were. A key the stored document lacks and whose draft value equals
 * the default-filled one stays out, so the document keeps following the pack's
 * defaults instead of freezing today's. `normalized` is `saved` with the defaults
 * applied, the same baseline `draft` started from. */
export function withoutUntouchedDefaults(
  draft: unknown,
  normalized: unknown,
  saved: unknown,
): unknown {
  if (!isPlainObject(draft) || !isPlainObject(normalized)) return draft;
  if (saved !== undefined && !isPlainObject(saved)) return draft;
  const stored = (saved ?? {}) as Json;
  const out: Json = {};
  for (const [key, value] of Object.entries(draft)) {
    if (value === undefined) continue;
    if (!(key in stored) && sameValue(value, normalized[key])) continue;
    out[key] = withoutUntouchedDefaults(value, normalized[key], stored[key]);
  }
  return out;
}
