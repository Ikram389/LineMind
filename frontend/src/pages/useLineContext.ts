import { useQuery } from "@tanstack/react-query";

import { getCurrentShift, getFactory, getLine } from "../api/endpoints.ts";
import { queryKeys } from "../api/queryKeys.ts";

/** The line, its factory and the current shift, shared by the line pages. */
export function useLineContext(lineId: number) {
  const line = useQuery({ queryKey: queryKeys.line(lineId), queryFn: () => getLine(lineId) });
  const factoryId = line.data?.factory;
  const factory = useQuery({
    queryKey: queryKeys.factory(factoryId ?? 0),
    queryFn: () => getFactory(factoryId as number),
    enabled: factoryId !== undefined,
  });
  const shift = useQuery({
    queryKey: queryKeys.currentShift(factoryId ?? 0),
    queryFn: () => getCurrentShift(factoryId as number),
    enabled: factoryId !== undefined,
    refetchInterval: 60_000, // pick up the next shift when this one ends
  });
  return { line, factory, shift };
}
