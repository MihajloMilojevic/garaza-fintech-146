import { createFileRoute } from "@tanstack/react-router";
import { Dashboard } from "@/components/Dashboard";
import { qk } from "@/lib/api/queries";

export const Route = createFileRoute("/transactions/$id")({
  ssr: false,
  head: ({ params }) => ({
    meta: [
      { title: `${params.id} — Risk Analysis` },
      { name: "description", content: `Risk analysis for screening ${params.id}.` },
      { property: "og:title", content: `${params.id} — Risk Analysis` },
      { property: "og:description", content: `Risk analysis for screening ${params.id}.` },
    ],
  }),
  loader: ({ context, params }) => {
    context.queryClient.ensureQueryData(qk.screening(params.id));
  },
  component: TransactionDetail,
  errorComponent: ({ error }) => (
    <div className="p-8 text-sm text-rose-600">Failed to load screening: {error.message}</div>
  ),
});

function TransactionDetail() {
  const { id } = Route.useParams();
  return <Dashboard screeningId={id} />;
}
