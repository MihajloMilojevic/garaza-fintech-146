import { createFileRoute } from "@tanstack/react-router";
import { Dashboard } from "@/components/Dashboard";
import { TRANSACTIONS } from "@/data/transactions";

export const Route = createFileRoute("/transactions/$id")({
  head: ({ params }) => {
    const tx = TRANSACTIONS.find((t) => t.id === params.id);
    const title = tx ? `${tx.id} — Risk Analysis` : "Transaction — Risk Analysis";
    const description = tx
      ? `Risk analysis for ${tx.id} (${tx.amount}, ${tx.merchant}).`
      : "Risk analysis for transaction.";
    return {
      meta: [
        { title },
        { name: "description", content: description },
        { property: "og:title", content: title },
        { property: "og:description", content: description },
      ],
    };
  },
  component: TransactionDetail,
});

function TransactionDetail() {
  const { id } = Route.useParams();
  return <Dashboard txId={id} />;
}