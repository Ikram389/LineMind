/** /dev/ui: every shared component on one page, to check looks in both themes (development only). */
import { Plus, Wrench } from "lucide-react";
import { useState } from "react";

import { Button } from "../components/ui/Button.tsx";
import { Card } from "../components/ui/Card.tsx";
import { SegmentedControl, Tabs } from "../components/ui/Choice.tsx";
import { type Column, DataTable } from "../components/ui/DataTable.tsx";
import { EmptyState, ErrorState, InlineNotice, Skeleton } from "../components/ui/Feedback.tsx";
import { Field, controlClass } from "../components/ui/Field.tsx";
import { FilterBar } from "../components/ui/FilterBar.tsx";
import { Dialog, Drawer } from "../components/ui/Overlay.tsx";
import { PageHeader } from "../components/ui/PageHeader.tsx";
import { StatCard } from "../components/ui/StatCard.tsx";
import { StatusBadge } from "../components/ui/StatusBadge.tsx";
import { type StatusKind, STATUS } from "../components/ui/status.ts";
import { Toast, Tooltip } from "../components/ui/Toast.tsx";
import { t } from "../i18n/t.ts";
import { type Theme, useTheme } from "../lib/theme.ts";

interface SampleRow {
  id: number;
  machine: string;
  minutes: number;
}

const ROWS: SampleRow[] = [
  { id: 1, machine: "Labeler", minutes: 12 },
  { id: 2, machine: "Filler", minutes: 4 },
  { id: 3, machine: "Capper", minutes: 7 },
];

const COLUMNS: Column<SampleRow>[] = [
  { key: "machine", header: t("table.machine"), render: (r) => r.machine, sortValue: (r) => r.machine },
  { key: "minutes", header: t("table.duration"), render: (r) => `${r.minutes} min`, sortValue: (r) => r.minutes, align: "right" },
];

export default function DevUiPage() {
  const [theme, setTheme] = useTheme();
  const [tab, setTab] = useState<"a" | "b">("a");
  const [overlay, setOverlay] = useState<"drawer" | "dialog" | null>(null);
  const [toast, setToast] = useState(false);

  return (
    <main className="flex flex-col gap-6 p-4 sm:p-6">
      <PageHeader
        title={t("dev.title")}
        subtitle={t("dev.subtitle")}
        actions={
          <SegmentedControl<Theme>
            label={t("theme.label")}
            value={theme}
            onChange={setTheme}
            options={[
              { value: "light", label: t("theme.light") },
              { value: "dark", label: t("theme.dark") },
            ]}
          />
        }
      />

      <Card title="Button">
        <div className="flex flex-wrap items-center gap-3">
          <Button variant="primary" icon={<Plus className="h-5 w-5" />}>
            {t("maint.create")}
          </Button>
          <Button>{t("table.export")}</Button>
          <Button variant="ghost">{t("prompt.later")}</Button>
          <Button variant="danger">{t("ui.close")}</Button>
          <Button variant="primary" size="lg">
            {t("alerts.acknowledge")}
          </Button>
          <Button disabled>{t("table.next")}</Button>
        </div>
      </Card>

      <Card title="StatusBadge">
        <div className="flex flex-wrap gap-2">
          {(Object.keys(STATUS) as StatusKind[]).map((kind) => (
            <StatusBadge key={kind} kind={kind} />
          ))}
        </div>
      </Card>

      <div className="grid gap-4 sm:grid-cols-3">
        <StatCard label={t("oee.oee")} value="78.4%" size="lg" />
        <StatCard label={t("qcard.defects")} value="165" trend={{ direction: "down", good: true, text: "−12%" }} />
        <StatCard label={t("qcard.rate")} value="3.0%" sub={t("time.zone", { zone: "Africa/Algiers" })} />
      </div>

      <Card title="FilterBar · Field · Tabs · SegmentedControl">
        <div className="flex flex-col gap-4">
          <FilterBar
            more={
              <Field label={t("table.reason")}>
                {(props) => <input {...props} className={controlClass} />}
              </Field>
            }
            actions={<Button variant="primary">{t("table.export")}</Button>}
          >
            <Field label={t("table.machine")} hint={t("theme.note")}>
              {(props) => (
                <select {...props} className={controlClass}>
                  <option>Labeler</option>
                </select>
              )}
            </Field>
          </FilterBar>
          <Tabs
            label={t("dev.title")}
            value={tab}
            onChange={setTab}
            options={[
              { value: "a", label: t("nav.downtime") },
              { value: "b", label: t("nav.quality") },
            ]}
          />
        </div>
      </Card>

      <Card title="DataTable">
        <DataTable columns={COLUMNS} rows={ROWS} rowKey={(r) => r.id} caption="DataTable" />
      </Card>

      <div className="grid gap-4 sm:grid-cols-2">
        <Card title="EmptyState · ErrorState">
          <EmptyState title={t("table.empty")} />
          <ErrorState />
        </Card>
        <Card title="Skeleton · InlineNotice">
          <div className="flex flex-col gap-3">
            <Skeleton />
            <InlineNotice tone="info">{t("theme.note")}</InlineNotice>
            <InlineNotice tone="warning">{t("oee.noShift")}</InlineNotice>
            <InlineNotice tone="critical">{t("panel.error")}</InlineNotice>
          </div>
        </Card>
      </div>

      <Card title="Drawer · Dialog · Toast · Tooltip">
        <div className="flex flex-wrap gap-3">
          <Button onClick={() => setOverlay("drawer")}>Drawer</Button>
          <Button onClick={() => setOverlay("dialog")}>Dialog</Button>
          <Button onClick={() => setToast(true)}>Toast</Button>
          <Tooltip label={t("appbar.maintenance")}>
            <Button variant="ghost" aria-label={t("appbar.maintenance")}>
              <Wrench aria-hidden className="h-5 w-5" />
            </Button>
          </Tooltip>
        </div>
      </Card>

      {overlay === "drawer" && (
        <Drawer title="Drawer" onClose={() => setOverlay(null)}>
          <EmptyState title={t("panel.empty")} />
        </Drawer>
      )}
      {overlay === "dialog" && (
        <Dialog
          title="Dialog"
          onClose={() => setOverlay(null)}
          footer={
            <>
              <Button onClick={() => setOverlay(null)}>{t("prompt.later")}</Button>
              <Button variant="primary" onClick={() => setOverlay(null)}>
                {t("settings.save")}
              </Button>
            </>
          }
        >
          <p className="text-body text-ink">{t("theme.note")}</p>
        </Dialog>
      )}
      {toast && <Toast message={t("settings.saved")} onClose={() => setToast(false)} />}
    </main>
  );
}
