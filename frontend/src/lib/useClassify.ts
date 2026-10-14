import { useMutation, useQueryClient } from "@tanstack/react-query";

import { bulkClassify, classifyEvent } from "../api/downtime.ts";
import { queryKeys } from "../api/queryKeys.ts";

interface ClassifyInput {
  eventIds: number[];
  reason: number;
  comment: string;
}

/** Save a classification (one stop or several) and refresh everything that depends on it. */
export function useClassify() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ eventIds, reason, comment }: ClassifyInput) =>
      eventIds.length === 1 && eventIds[0] !== undefined
        ? classifyEvent(eventIds[0], reason, comment).then(() => 1)
        : bulkClassify(eventIds, reason, comment).then((r) => r.classified),
    onSuccess: () => {
      // Badge count, queue, Pareto, summary, table, incident drawers.
      void queryClient.invalidateQueries({ queryKey: queryKeys.downtime });
      void queryClient.invalidateQueries({ queryKey: ["incident"] });
      void queryClient.invalidateQueries({ queryKey: ["machineDowntime"] });
    },
  });
}
