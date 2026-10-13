import { useQuery } from "@tanstack/react-query";
import { Link, Navigate } from "react-router";

import { listLines } from "../api/endpoints.ts";
import { queryKeys } from "../api/queryKeys.ts";
import { Panel } from "../components/Panel.tsx";
import { t } from "../i18n/t.ts";

export function LinePickerPage() {
  const lines = useQuery({ queryKey: queryKeys.lines, queryFn: listLines });

  // Only one line: go straight to it.
  if (lines.data?.length === 1 && lines.data[0]) {
    return <Navigate to={`/lines/${lines.data[0].id}`} replace />;
  }

  return (
    <main className="mx-auto max-w-3xl p-6">
      <Panel
        title={t("picker.title")}
        isLoading={lines.isLoading}
        isError={lines.isError}
        isEmpty={lines.data?.length === 0}
        emptyText={t("picker.empty")}
      >
        <ul className="flex flex-col gap-3">
          {lines.data?.map((line) => (
            <li key={line.id}>
              <Link
                to={`/lines/${line.id}`}
                className="block rounded-lg border border-gray-300 p-4 text-2xl font-semibold hover:bg-gray-50"
              >
                {line.name}
              </Link>
            </li>
          ))}
        </ul>
      </Panel>
    </main>
  );
}
