"use client";

import { useEffect } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { queryKeys } from "./query";

// Invalidate derived views when a freshly fetched delivery reports publication.
// The DB status stays in Query; this hook owns no worker or local job state.
export function useRPublicationRefresh(storeId: number | null, publishedVersions: string) {
  const client = useQueryClient();
  useEffect(() => {
    if (!storeId || !publishedVersions) return;
    void client.invalidateQueries({ queryKey: queryKeys.faqs(storeId) });
    void client.invalidateQueries({ queryKey: queryKeys.roadmapRoot(storeId) });
  }, [client, storeId, publishedVersions]);
}
