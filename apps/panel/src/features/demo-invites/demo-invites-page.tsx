import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { type FormEvent, useState } from "react";
import { api, unwrap } from "@/api/client";
import type { components } from "@/api/schema";
import { ConfirmDialog } from "@/components/confirm-dialog";
import { EmptyState } from "@/components/empty-state";
import { ErrorState } from "@/components/error-state";
import { PageHeader } from "@/components/page-header";
import { TimeAgo } from "@/components/time-ago";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { errorDetail } from "@/lib/errors";
import { LIVE, qk } from "@/lib/queries";
import { useApiMutation } from "@/lib/use-api-mutation";

type Invite = components["schemas"]["DemoInviteOut"];

const PAGE = 50;

function status(invite: Invite): {
  label: string;
  variant: "default" | "secondary" | "destructive" | "outline";
} {
  if (invite.revoked_at) return { label: "Revocada", variant: "destructive" };
  if (invite.expires_at && new Date(invite.expires_at) <= new Date())
    return { label: "Caducada", variant: "outline" };
  if (invite.uses >= invite.max_uses)
    return { label: "Agotada", variant: "outline" };
  return { label: "Activa", variant: "default" };
}

function CreateInviteForm() {
  const [note, setNote] = useState("");
  const [maxUses, setMaxUses] = useState("1");
  const [expiresInDays, setExpiresInDays] = useState("7");
  const [neverExpires, setNeverExpires] = useState(false);
  const mutation = useApiMutation({
    fn: () =>
      unwrap(
        api.POST("/demo/invites", {
          body: {
            note,
            max_uses: Number(maxUses) || 1,
            expires_in_days: neverExpires ? null : Number(expiresInDays) || 1,
          },
        }),
      ),
    success: "Invitación creada.",
    invalidate: [qk.demoInvites()],
    onSuccess: () => setNote(""),
  });
  function submit(event: FormEvent) {
    event.preventDefault();
    mutation.mutate();
  }
  return (
    <Card>
      <CardContent className="pt-6">
        <form onSubmit={submit} className="flex flex-wrap items-end gap-4">
          <div className="grid gap-2">
            <Label htmlFor="invite-note">Nota (para quién es)</Label>
            <Input
              id="invite-note"
              maxLength={200}
              placeholder="p. ej. peluquero Juan"
              value={note}
              onChange={(event) => setNote(event.target.value)}
            />
          </div>
          <div className="grid gap-2">
            <Label htmlFor="invite-max-uses">Usos</Label>
            <Input
              id="invite-max-uses"
              type="number"
              min={1}
              max={1000}
              className="w-20"
              value={maxUses}
              onChange={(event) => setMaxUses(event.target.value)}
            />
          </div>
          <div className="grid gap-2">
            <Label htmlFor="invite-expires">Caduca en (días)</Label>
            <Input
              id="invite-expires"
              type="number"
              min={1}
              max={365}
              className="w-24"
              disabled={neverExpires}
              value={expiresInDays}
              onChange={(event) => setExpiresInDays(event.target.value)}
            />
          </div>
          <label className="flex items-center gap-2 pb-2 text-sm text-muted-foreground">
            <input
              type="checkbox"
              checked={neverExpires}
              onChange={(event) => setNeverExpires(event.target.checked)}
            />
            No caduca
          </label>
          <Button type="submit" disabled={mutation.isPending}>
            Crear invitación
          </Button>
        </form>
        {mutation.isError && (
          <p role="alert" className="mt-2 text-sm text-destructive">
            {errorDetail(mutation.error, "No se pudo crear la invitación.")}
          </p>
        )}
      </CardContent>
    </Card>
  );
}

function RevokeAction({ invite }: { invite: Invite }) {
  const [open, setOpen] = useState(false);
  const mutation = useApiMutation({
    fn: () =>
      unwrap(
        api.POST("/demo/invites/{id}/revoke", {
          params: { path: { id: invite.id } },
        }),
      ),
    success: "Invitación revocada.",
    invalidate: [qk.demoInvites()],
    onSuccess: () => setOpen(false),
  });
  if (invite.revoked_at) return null;
  return (
    <>
      <Button size="sm" variant="outline" onClick={() => setOpen(true)}>
        Revocar
      </Button>
      <ConfirmDialog
        open={open}
        onOpenChange={setOpen}
        title="Revocar invitación"
        description="Nadie podrá canjear este código a partir de ahora. Quien ya haya entrado con él conserva su acceso hasta que caduque."
        confirmLabel="Revocar"
        onConfirm={() => mutation.mutate()}
      />
      {mutation.isError && (
        <p role="alert">{errorDetail(mutation.error, "No se pudo revocar.")}</p>
      )}
    </>
  );
}

function InviteQr({ invite }: { invite: Invite }) {
  const [open, setOpen] = useState(false);
  // Drawn by the backend only when someone opens it, never for every row.
  const qr = useQuery({
    queryKey: qk.demoInviteQr(invite.id),
    queryFn: () =>
      unwrap(
        api.GET("/demo/invites/{id}/qr", {
          params: { path: { id: invite.id } },
        }),
      ),
    enabled: open && invite.telegram_link !== null,
    staleTime: Number.POSITIVE_INFINITY,
  });
  if (!open) {
    return (
      <Button size="sm" variant="outline" onClick={() => setOpen(true)}>
        Ver código
      </Button>
    );
  }
  return (
    <div className="space-y-2">
      <Button size="sm" variant="outline" onClick={() => setOpen(false)}>
        Ocultar
      </Button>
      <p className="font-mono text-sm">{invite.code}</p>
      {invite.telegram_link ? (
        <>
          <p className="text-sm break-all">{invite.telegram_link}</p>
          {qr.isError && (
            <p role="alert" className="text-sm text-destructive">
              {errorDetail(qr.error, "No se pudo generar el QR.")}
            </p>
          )}
          {qr.data?.qr_svg && (
            <div className="h-40 w-40 [&>svg]:h-full [&>svg]:w-full">
              {/* biome-ignore lint/security/noDangerouslySetInnerHtml: our own SVG, from the backend's QR generator (tools/ops/qr.py), never user-supplied markup. */}
              <div dangerouslySetInnerHTML={{ __html: qr.data.qr_svg }} />
            </div>
          )}
        </>
      ) : (
        <p className="text-sm text-muted-foreground">
          Configura DEMO_TELEGRAM_BOT_USERNAME para generar el enlace y el QR;
          de momento solo hay código.
        </p>
      )}
    </div>
  );
}

export function DemoInvitesPage() {
  const query = useInfiniteQuery({
    queryKey: qk.demoInvites(),
    ...LIVE,
    initialPageParam: "",
    queryFn: ({ pageParam }) =>
      unwrap(
        api.GET("/demo/invites", {
          params: { query: { limit: PAGE, cursor: pageParam } },
        }),
      ),
    getNextPageParam: (last) => last.next_cursor ?? undefined,
  });
  const invites = query.data?.pages.flatMap((page) => page.items) ?? [];
  return (
    <div className="space-y-6">
      <PageHeader
        title="Invitaciones de demo"
        help="procedimientos/demo/"
        description="Acceso a la demo por código, sin tocar el .env del servidor."
      />
      <CreateInviteForm />
      {query.isPending ? (
        <p>Cargando invitaciones…</p>
      ) : query.isError ? (
        <ErrorState
          message={errorDetail(
            query.error,
            "No se pudieron cargar las invitaciones.",
          )}
          onRetry={() => void query.refetch()}
        />
      ) : invites.length === 0 ? (
        <EmptyState message="No hay invitaciones todavía." />
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              {[
                "Nota",
                "Usos",
                "Caduca",
                "Estado",
                "Creada",
                "Código",
                "Acciones",
              ].map((label) => (
                <TableHead key={label}>{label}</TableHead>
              ))}
            </TableRow>
          </TableHeader>
          <TableBody>
            {invites.map((invite) => {
              const s = status(invite);
              return (
                <TableRow key={invite.id}>
                  <TableCell>{invite.note || "—"}</TableCell>
                  <TableCell>
                    {invite.uses}/{invite.max_uses}
                  </TableCell>
                  <TableCell>
                    {invite.expires_at ? (
                      <TimeAgo date={invite.expires_at} />
                    ) : (
                      "Nunca"
                    )}
                  </TableCell>
                  <TableCell>
                    <Badge variant={s.variant}>{s.label}</Badge>
                  </TableCell>
                  <TableCell>
                    <TimeAgo date={invite.created_at} />
                  </TableCell>
                  <TableCell>
                    <InviteQr invite={invite} />
                  </TableCell>
                  <TableCell>
                    <RevokeAction invite={invite} />
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      )}
      {query.hasNextPage && (
        <Button
          variant="outline"
          disabled={query.isFetchingNextPage}
          onClick={() => void query.fetchNextPage()}
        >
          Cargar más
        </Button>
      )}
    </div>
  );
}
