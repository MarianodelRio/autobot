import { EmptyState } from "./empty-state";
import { PageHeader } from "./page-header";

export function ComingSoonPage({ title }: { title: string }) {
  return (
    <div>
      <PageHeader title={title} />
      <EmptyState message="Próximamente." />
    </div>
  );
}
