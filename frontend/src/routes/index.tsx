import { createFileRoute } from "@tanstack/react-router";
import { TransactionsList } from "@/components/TransactionsList";
import { qk } from "@/lib/api/queries";

export const Route = createFileRoute("/")({
  ssr: false,
  head: () => ({
    meta: [
      { title: "Nexus — Screening Queue" },
      { name: "description", content: "Browse screening events and dive into risk analysis for each one." },
      { property: "og:title", content: "Nexus — Screening Queue" },
      { property: "og:description", content: "Browse screening events and dive into risk analysis for each one." },
    ],
  }),
  loader: ({ context }) => {
    context.queryClient.ensureQueryData(qk.screeningList({ limit: 50 }));
  },
  component: Index,
  errorComponent: ({ error }) => (
    <div className="p-8 text-sm text-rose-600">Failed to load: {error.message}</div>
  ),
});

function Index() {
  return <TransactionsList />;
}
