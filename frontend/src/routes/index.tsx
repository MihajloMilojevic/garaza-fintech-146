import { createFileRoute } from "@tanstack/react-router";
import { TransactionsList } from "@/components/TransactionsList";
import { qk } from "@/lib/api/queries";
import type { Verdict } from "@/lib/api/client";

type IndexSearch = {
  verdict?: Verdict;
  page?: number;
};

export const Route = createFileRoute("/")({
  ssr: false,
  validateSearch: (search: Record<string, unknown>): IndexSearch => ({
    verdict: (["BLOCK", "REVIEW", "CLEAR"].includes(search.verdict as string)
      ? (search.verdict as Verdict)
      : undefined),
    page: Number(search.page) > 0 ? Math.floor(Number(search.page)) : 1,
  }),
  head: () => ({
    meta: [
      { title: "Nexus — Screening Queue" },
      { name: "description", content: "Browse screening events and dive into risk analysis for each one." },
      { property: "og:title", content: "Nexus — Screening Queue" },
      { property: "og:description", content: "Browse screening events and dive into risk analysis for each one." },
    ],
  }),
  loader: ({ context }) => {
    context.queryClient.ensureQueryData(
      qk.screeningList({ limit: 20, page: 1 }),
    );
  },
  component: Index,
  errorComponent: ({ error }) => (
    <div className="p-8 text-sm text-rose-600">Failed to load: {error.message}</div>
  ),
});

function Index() {
  return <TransactionsList />;
}
