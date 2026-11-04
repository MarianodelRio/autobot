import { sql } from "@codemirror/lang-sql";
import { yaml } from "@codemirror/lang-yaml";
import CodeMirror from "@uiw/react-codemirror";

export type CodeEditorLanguage = "sql" | "yaml";

export default function CodeEditorInner({
  value,
  onChange,
  language,
  readOnly,
  sqlSchema,
  onRun,
}: {
  value: string;
  onChange?: (value: string) => void;
  language: CodeEditorLanguage;
  readOnly?: boolean;
  /** Table -> column names, for SQL autocompletion against the data catalogue. */
  sqlSchema?: Record<string, string[]>;
  /** Called on ⌘Enter / Ctrl+Enter, e.g. to run the query. */
  onRun?: () => void;
}) {
  return (
    <CodeMirror
      value={value}
      onChange={onChange}
      extensions={[language === "sql" ? sql({ schema: sqlSchema }) : yaml()]}
      theme="dark"
      readOnly={readOnly}
      onKeyDown={(event) => {
        if (
          onRun &&
          (event.metaKey || event.ctrlKey) &&
          event.key === "Enter"
        ) {
          event.preventDefault();
          onRun();
        }
      }}
    />
  );
}
