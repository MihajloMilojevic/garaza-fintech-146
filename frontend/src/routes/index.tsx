import { createFileRoute } from "@tanstack/react-router";
import { TransactionsList } from "@/components/TransactionsList";

export const Route = createFileRoute("/")({
  head: () => ({
    meta: [
      { title: "Nexus — Transactions Dashboard" },
      { name: "description", content: "Browse all transactions and dive into risk analysis for each one." },
      { property: "og:title", content: "Nexus — Transactions Dashboard" },
      { property: "og:description", content: "Browse all transactions and dive into risk analysis for each one." },
    ],
  }),
  component: Index,
});

function Index() {
  return <TransactionsList />;
}
