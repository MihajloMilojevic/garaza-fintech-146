import { Link } from "@tanstack/react-router";

const ITEMS = [
  { to: "/", label: "Screening" },
  { to: "/dashboard", label: "Dashboard" },
  { to: "/accounts", label: "Accounts" },
  { to: "/screen", label: "Live Screener" },
] as const;

export function TopNav() {
  return (
    <nav className="flex flex-wrap items-center gap-2 rounded-2xl border border-slate-200 bg-white p-2 shadow-sm">
      <span className="px-3 py-1 text-xs font-bold uppercase tracking-[0.2em] text-slate-400">
        Nexus AML
      </span>
      {ITEMS.map((it) => (
        <Link
          key={it.to}
          to={it.to}
          activeOptions={{ exact: it.to === "/" }}
          className="rounded-lg px-3 py-1.5 text-sm font-semibold text-slate-600 transition-colors hover:bg-slate-100"
          activeProps={{
            className:
              "rounded-lg px-3 py-1.5 text-sm font-semibold bg-[#c8102e] text-white shadow-sm",
          }}
        >
          {it.label}
        </Link>
      ))}
    </nav>
  );
}