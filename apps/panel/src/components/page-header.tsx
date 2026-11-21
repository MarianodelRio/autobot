import type { ReactNode } from "react";
import { HelpLink } from "./help-link";

export function PageHeader({
  title,
  description,
  actions,
  help,
}: {
  title: string;
  description?: ReactNode;
  actions?: ReactNode;
  /** Docs page of this screen (relative to /docs/); shows the «?» link. */
  help?: string;
}) {
  return (
    <div className="flex items-start justify-between gap-4 pb-6">
      <div>
        <div className="flex items-center gap-2">
          <h1 className="text-xl font-semibold">{title}</h1>
          {help && <HelpLink page={help} />}
        </div>
        {description && (
          <p className="text-sm text-muted-foreground">{description}</p>
        )}
      </div>
      {actions}
    </div>
  );
}
