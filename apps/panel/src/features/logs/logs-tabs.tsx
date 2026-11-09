import { PageHeader } from "@/components/page-header";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { ConversationsTab } from "./conversations-tab";
import { OperatorTab } from "./operator-tab";
import { TechnicalTab } from "./technical-tab";

export type LogsTab = "technical" | "conversations" | "operator";

export interface LogsSearch {
  tab: LogsTab;
  tenant: string;
  level: string;
  service: string;
  q: string;
  start: string;
  end: string;
  kinds: string;
  status: string;
  action: string;
}

export function LogsTabs({
  search,
  onChange,
  onTabChange,
}: {
  search: LogsSearch;
  onChange: (next: Partial<LogsSearch>) => void;
  onTabChange: (tab: LogsTab) => void;
}) {
  return (
    <div className="space-y-6">
      <PageHeader title="Logs" />
      <Tabs
        value={search.tab}
        onValueChange={(value) => onTabChange(value as LogsTab)}
      >
        <TabsList>
          <TabsTrigger value="technical">Técnicos</TabsTrigger>
          <TabsTrigger value="conversations">Conversaciones</TabsTrigger>
          <TabsTrigger value="operator">Operador</TabsTrigger>
        </TabsList>
        <TabsContent value="technical">
          <TechnicalTab
            filters={{
              tenant: search.tenant,
              level: search.level,
              service: search.service,
              q: search.q,
              start: search.start,
              end: search.end,
            }}
            onFilterChange={onChange}
          />
        </TabsContent>
        <TabsContent value="conversations">
          <ConversationsTab
            filters={{
              tenant: search.tenant,
              kinds: search.kinds,
              status: search.status,
            }}
            onFilterChange={onChange}
          />
        </TabsContent>
        <TabsContent value="operator">
          <OperatorTab
            filters={{ tenant: search.tenant, action: search.action }}
            onFilterChange={onChange}
          />
        </TabsContent>
      </Tabs>
    </div>
  );
}
