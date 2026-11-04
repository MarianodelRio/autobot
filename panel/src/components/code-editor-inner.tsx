import { sql } from "@codemirror/lang-sql";
import { yaml } from "@codemirror/lang-yaml";
import CodeMirror from "@uiw/react-codemirror";

export type CodeEditorLanguage = "sql" | "yaml";

export default function CodeEditorInner({
  value,
  onChange,
  language,
  readOnly,
}: {
  value: string;
  onChange?: (value: string) => void;
  language: CodeEditorLanguage;
  readOnly?: boolean;
}) {
  return (
    <CodeMirror
      value={value}
      onChange={onChange}
      extensions={[language === "sql" ? sql() : yaml()]}
      theme="dark"
      readOnly={readOnly}
    />
  );
}
