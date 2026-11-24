import { expect, test } from "vitest";
import {
  getPath,
  mergePaths,
  pickPaths,
  sameValue,
  schemaAt,
  sectionSchema,
  setPath,
  withoutUntouchedDefaults,
} from "./form-draft";

test("sameValue ignores key order and undefined keys", () => {
  expect(
    sameValue({ a: 1, b: { c: [1, 2] } }, { b: { c: [1, 2] }, a: 1 }),
  ).toBe(true);
  expect(sameValue({ a: 1, b: undefined }, { a: 1 })).toBe(true);
  expect(sameValue({ a: [1, 2] }, { a: [2, 1] })).toBe(false);
  expect(sameValue({ a: null }, { a: undefined })).toBe(false);
});

test("paths are read, written, picked and merged without touching the rest", () => {
  const doc = { name: "A", config: { price: 1, texts: { hi: "Hola" } } };
  expect(getPath(doc, "config.texts.hi")).toBe("Hola");
  expect(getPath(doc, "config.missing.deep")).toBeUndefined();
  expect(setPath(doc, "config.price", 2)).toEqual({
    name: "A",
    config: { price: 2, texts: { hi: "Hola" } },
  });
  expect(doc.config.price).toBe(1); // a copy, never in place
  expect(pickPaths(doc, ["name", "config.price"])).toEqual({
    name: "A",
    config: { price: 1 },
  });
  expect(
    mergePaths(doc, { config: { price: 3 } }, ["config.price", "name"]),
  ).toEqual({
    config: { price: 3, texts: { hi: "Hola" } },
  });
});

const ROOT = {
  type: "object",
  required: ["name"],
  properties: {
    name: { type: "string", title: "Nombre" },
    privacy: { $ref: "#/$defs/Privacy", title: "Privacidad" },
    config: {
      type: "object",
      title: "SalonConfig",
      required: ["price"],
      properties: {
        price: { type: "number", title: "Precio" },
        hours: { type: "number", title: "Horas" },
      },
    },
  },
  $defs: {
    Privacy: {
      type: "object",
      title: "Privacy",
      description: "In English",
      properties: { url: { type: "string", title: "Enlace" } },
    },
  },
};

test("schemaAt follows nesting and $refs, and misses unknown fields", () => {
  expect(schemaAt(ROOT, "config.price")).toEqual({
    type: "number",
    title: "Precio",
  });
  expect(schemaAt(ROOT, "privacy.url")).toEqual({
    type: "string",
    title: "Enlace",
  });
  expect(schemaAt(ROOT, "config.business_name")).toBeUndefined();
});

test("a section schema keeps only its fields, their required marks and $defs", () => {
  const schema = sectionSchema(ROOT, ["name", "config.price"]);
  expect(schema).toEqual({
    type: "object",
    required: ["name"],
    $defs: ROOT.$defs,
    properties: {
      name: { type: "string", title: "Nombre" },
      // An untitled wrapper: the pack's model name never shows as a heading.
      config: {
        type: "object",
        required: ["price"],
        properties: { price: { type: "number", title: "Precio" } },
      },
    },
  });
});

test("a section made of one object field drops that field's own title", () => {
  const schema = sectionSchema(ROOT, ["privacy"]);
  const privacy = (schema.properties as Record<string, Record<string, unknown>>)
    .privacy;
  expect(privacy?.title).toBeUndefined();
  expect(privacy?.description).toBeUndefined();
  expect(privacy?.properties).toEqual({
    url: { type: "string", title: "Enlace" },
  });
});

test("saving leaves untouched defaults out and keeps every real change", () => {
  const saved = { name: "A", config: { price: 1 } };
  const normalized = {
    name: "A",
    config: { price: 1, texts: { hi: "Hola", bye: "Adiós" }, days: 14 },
  };
  // Nothing touched: exactly the stored document.
  expect(withoutUntouchedDefaults(normalized, normalized, saved)).toEqual(
    saved,
  );
  // A changed default is kept, its untouched siblings are not.
  expect(
    withoutUntouchedDefaults(
      {
        ...normalized,
        config: { ...normalized.config, texts: { hi: "Buenas", bye: "Adiós" } },
      },
      normalized,
      saved,
    ),
  ).toEqual({ name: "A", config: { price: 1, texts: { hi: "Buenas" } } });
  // A stored value equal to the default stays: it was written on purpose.
  expect(
    withoutUntouchedDefaults(
      { name: "A", config: { price: 1, days: 14 } },
      { name: "A", config: { price: 1, days: 14 } },
      { name: "A", config: { price: 1, days: 14 } },
    ),
  ).toEqual({ name: "A", config: { price: 1, days: 14 } });
  // A field removed from the draft is removed.
  expect(
    withoutUntouchedDefaults({ config: { price: 1 } }, normalized, saved),
  ).toEqual({
    config: { price: 1 },
  });
});
