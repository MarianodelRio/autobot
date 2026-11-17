import { toast } from "sonner";

export function CopyButton({
  value,
  label = "Copiar",
}: {
  value: string;
  label?: string;
}) {
  return (
    <button
      type="button"
      aria-label={label}
      className="text-muted-foreground hover:text-foreground"
      onClick={() => {
        void navigator.clipboard?.writeText(value);
        toast.success("Copiado.");
      }}
    >
      ⧉
    </button>
  );
}
