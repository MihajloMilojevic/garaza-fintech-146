import { queryOptions } from "@tanstack/react-query";
import { apiClient, type ScreeningContext } from "./client";

export const qk = {
  dashboardStats: () =>
    queryOptions({ queryKey: ["dashboard", "stats"], queryFn: () => apiClient.dashboardStats() }),

  accounts: (p: {
    page?: number;
    limit?: number;
    risk_band?: string;
    verdict?: string;
    search?: string;
  }) =>
    queryOptions({
      queryKey: ["accounts", p],
      queryFn: () => apiClient.listAccounts(p),
    }),

  account: (id: string) =>
    queryOptions({ queryKey: ["account", id], queryFn: () => apiClient.account(id) }),

  accountTxs: (
    id: string,
    p: { page?: number; limit?: number; from?: string; to?: string } = {},
  ) =>
    queryOptions({
      queryKey: ["account", id, "transactions", p],
      queryFn: () => apiClient.accountTransactions(id, p),
    }),

  screeningList: (
    p: {
      page?: number;
      limit?: number;
      verdict?: string;
      context?: ScreeningContext;
      min_match_score?: number;
      verdicts_differ?: boolean;
    } = {},
  ) =>
    queryOptions({
      queryKey: ["screening", "list", p],
      queryFn: () => apiClient.listScreening(p),
    }),

  screening: (id: string) =>
    queryOptions({ queryKey: ["screening", id], queryFn: () => apiClient.screening(id) }),

  thresholdExplain: (id: string) =>
    queryOptions({ queryKey: ["threshold", id], queryFn: () => apiClient.thresholdExplain(id) }),
};