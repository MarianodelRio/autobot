import { useNavigate } from "@tanstack/react-router";
import { useEffect } from "react";
import {
  CommandDialog,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/ui/command";
import { useOverview } from "@/features/overview/use-overview";
import { AUDIT_SECTION, NAV_SECTIONS } from "./nav-sections";

export function CommandMenu({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const navigate = useNavigate();
  const { data } = useOverview();

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "k" && (event.metaKey || event.ctrlKey)) {
        event.preventDefault();
        onOpenChange(!open);
      }
    }
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [open, onOpenChange]);

  function go(to: string) {
    onOpenChange(false);
    navigate({ to });
  }

  return (
    <CommandDialog
      open={open}
      onOpenChange={onOpenChange}
      title="Saltar a…"
      description="Secciones"
    >
      <CommandInput placeholder="Buscar una sección…" />
      <CommandList>
        <CommandEmpty>Sin resultados.</CommandEmpty>
        <CommandGroup heading="Secciones">
          {[...NAV_SECTIONS, AUDIT_SECTION].map((section) => (
            <CommandItem key={section.to} onSelect={() => go(section.to)}>
              <section.icon />
              <span>{section.title}</span>
            </CommandItem>
          ))}
        </CommandGroup>
        {data && data.tenant_rows.length > 0 && (
          <CommandGroup heading="Clientes">
            {data.tenant_rows.map((tenant) => (
              <CommandItem
                key={tenant.slug}
                value={`${tenant.name} ${tenant.slug}`}
                onSelect={() =>
                  go(`/clientes/${encodeURIComponent(tenant.slug)}`)
                }
              >
                {tenant.name}
              </CommandItem>
            ))}
          </CommandGroup>
        )}
      </CommandList>
    </CommandDialog>
  );
}
