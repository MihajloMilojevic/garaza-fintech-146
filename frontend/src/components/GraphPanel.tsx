import { useEffect, useMemo, useRef, useState } from "react";

export type GraphNode = {
  id: string;
  label: string;
  x: number;
  y: number;
  radius: number;
  risk: "low" | "medium" | "high";
  type: string;
  value: string;
  country: string;
  riskScore: number;
  flags: string[];
  description: string;
};

export type Edge = { from: string; to: string };

export const NODES: GraphNode[] = [
  { id: "tx",       label: "Transaction",  x: 50, y: 50, radius: 28, risk: "high",   type: "Payment",     value: "$12,480.00", country: "—",   riskScore: 87, flags: ["Velocity", "Geo Mismatch", "High Amount"], description: "Outbound wire transfer flagged by multiple risk rules." },
  { id: "user",     label: "Transaction",  x: 22, y: 28, radius: 20, risk: "medium", type: "Account",     value: "u_19283",    country: "DE",  riskScore: 54, flags: ["New Device"], description: "Account holder initiating the transfer." },
  { id: "device",   label: "Transaction",  x: 78, y: 28, radius: 18, risk: "high",   type: "Endpoint",    value: "iPhone 15",  country: "NG",  riskScore: 78, flags: ["First Seen", "Rooted"], description: "Device used to authorize the transaction." },
  { id: "ip",       label: "Transaction",  x: 92, y: 50, radius: 16, risk: "high",   type: "Network",     value: "41.58.x.x",  country: "NG",  riskScore: 81, flags: ["VPN", "TOR Exit"], description: "Originating network endpoint." },
  { id: "card",     label: "Transaction",  x: 18, y: 72, radius: 18, risk: "medium", type: "Instrument",  value: "•••• 4421",  country: "DE",  riskScore: 46, flags: ["CVV Retry"], description: "Card used as funding source." },
  { id: "merchant", label: "Transaction",  x: 82, y: 72, radius: 18, risk: "high",   type: "Counterparty",value: "ACME Ltd.",  country: "RU",  riskScore: 74, flags: ["Sanctions Watch"], description: "Beneficiary account receiving funds." },
  { id: "bank",     label: "Transaction",  x: 50, y: 86, radius: 16, risk: "low",    type: "Institution", value: "Deutsche Bank", country: "DE", riskScore: 12, flags: [], description: "Issuing financial institution." },
  { id: "session",  label: "Transaction",  x: 38, y: 14, radius: 15, risk: "medium", type: "Auth",        value: "s_77a21",    country: "DE",  riskScore: 41, flags: ["Short TTL"], description: "Authenticated session that approved the transfer." },
  { id: "email",    label: "Transaction",  x: 8,  y: 50, radius: 15, risk: "low",    type: "Identity",    value: "j.doe@…",    country: "DE",  riskScore: 18, flags: [], description: "Contact email associated with the account." },
];

export const EDGES: Edge[] = [
  { from: "tx", to: "user" },
  { from: "tx", to: "device" },
  { from: "tx", to: "ip" },
  { from: "tx", to: "card" },
  { from: "tx", to: "merchant" },
  { from: "tx", to: "bank" },
  { from: "user", to: "session" },
  { from: "user", to: "email" },
  { from: "user", to: "card" },
  { from: "device", to: "ip" },
  { from: "device", to: "session" },
  { from: "card", to: "bank" },
];

export const RISK_COLORS: Record<GraphNode["risk"], { from: string; to: string; solid: string; text: string; label: string }> = {
  low:     { from: "#a7f3d0", to: "#10b981", solid: "#10b981", text: "Low Risk",    label: "LOW" },
  medium:  { from: "#fef3c7", to: "#f59e0b", solid: "#f59e0b", text: "For Review", label: "MED" },
  high:    { from: "#fee2e2", to: "#ef4444", solid: "#ef4444", text: "High Risk",   label: "HIGH" },
};

const NODE_STYLES = `
  .graph-node {
    position: relative;
    background: #0f172a;
    border: 1.5px solid #334155;
    box-shadow:
      inset 0 1px 0 0 rgba(255,255,255,0.08),
      inset 0 -8px 16px -2px rgba(0,68,254,0.18),
      0 4px 12px rgba(15,23,42,0.35);
    transition: all 200ms cubic-bezier(0.4, 0, 0.2, 1);
    display: flex;
    align-items: center;
    justify-content: center;
    text-align: center;
    overflow: hidden;
  }

  .graph-node::before {
    content: "";
    position: absolute;
    inset: 0;
    border-radius: 50%;
    opacity: 0.45;
    background-image: url("data:image/svg+xml,%3Csvg viewBox='0 0 200 200' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='noiseFilter'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.95' numOctaves='4' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23noiseFilter)' opacity='1'/%3E%3C/svg%3E");
    mix-blend-mode: overlay;
    pointer-events: none;
  }

  .graph-node:hover {
    transform: scale(1.06);
    border-color: #475569;
    box-shadow:
      inset 0 1px 0 0 rgba(255,255,255,0.12),
      inset 0 -10px 20px 0px rgba(0,68,254,0.28),
      0 6px 18px rgba(0,68,254,0.15);
  }
`;

type Props = {
  selectedId: string | null;
  onSelect: (id: string | null) => void;
  nodes?: GraphNode[];
  edges?: Edge[];
};

export function GraphPanel({ selectedId, onSelect, nodes, edges }: Props) {
  const graphNodes = nodes ?? NODES;
  const graphEdges = edges ?? EDGES;
  const [hover, setHover] = useState<string | null>(null);
  const [tick, setTick] = useState(0);
  const raf = useRef<number | null>(null);

  // --- DRAG STATE ---
  const [isDragging, setIsDragging] = useState(false);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const dragStart = useRef({ x: 0, y: 0 });
  const svgRef = useRef<SVGSVGElement | null>(null);

  // --- ZOOM STATE ---
  const [zoom, setZoom] = useState(1.25);

  useEffect(() => {
    const styleEl = document.createElement("style");
    styleEl.textContent = NODE_STYLES;
    document.head.appendChild(styleEl);
    return () => { document.head.removeChild(styleEl); };
  }, []);

  useEffect(() => {
    let mounted = true;
    const loop = () => {
      if (!mounted) return;
      setTick((t) => (t + 1) % 10000);
      raf.current = requestAnimationFrame(loop);
    };
    raf.current = requestAnimationFrame(loop);
    return () => {
      mounted = false;
      if (raf.current) cancelAnimationFrame(raf.current);
    };
  }, []);

  const nodeMap = useMemo(() => Object.fromEntries(graphNodes.map((n) => [n.id, n])), [graphNodes]);
  const focus = hover ?? selectedId;
  const connected = useMemo(() => {
    if (!focus) return new Set<string>();
    const set = new Set<string>([focus]);
    graphEdges.forEach((e) => {
      if (e.from === focus) set.add(e.to);
      if (e.to === focus) set.add(e.from);
    });
    return set;
  }, [focus, graphEdges]);

  const float = (i: number, dim: "x" | "y") => {
    const n = graphNodes[i];
    const offset = dim === "x"
      ? Math.sin(tick / 120 + i * 1.7) * 1.2
      : Math.sin(tick / 140 + i * 2.3) * 0.9;
    return dim === "x" ? n.x + offset : n.y + offset;
  };

  // --- DRAG HANDLERS ---
  const handleMouseDown = (e: React.MouseEvent<SVGSVGElement>) => {
    if ((e.target as SVGElement).closest(".graph-node-container")) return;
    setIsDragging(true);
    dragStart.current = { x: e.clientX - pan.x, y: e.clientY - pan.y };
  };

  const handleMouseMove = (e: React.MouseEvent<SVGSVGElement>) => {
    if (!isDragging) return;
    setPan({
      x: e.clientX - dragStart.current.x,
      y: e.clientY - dragStart.current.y,
    });
  };

  const handleMouseUpOrLeave = () => { setIsDragging(false); };

  // --- WHEEL ZOOM HANDLER ---
  const handleWheel = (e: React.WheelEvent<SVGSVGElement>) => {
    e.preventDefault();
    setZoom((prev) => Math.min(Math.max(prev - e.deltaY * 0.001, 0.4), 3));
  };

  const vbSize = 1000 / zoom;
  const vbOffset = (1000 - vbSize) / 2;

  return (
    <div className="relative h-full w-full bg-white overflow-hidden select-none">
      <svg
        ref={svgRef}
        viewBox={`${vbOffset} ${vbOffset} ${vbSize} ${vbSize}`}
        preserveAspectRatio="xMidYMid meet"
        className={`absolute inset-0 h-full w-full z-10 ${isDragging ? "cursor-grabbing" : "cursor-grab"}`}
        shapeRendering="geometricPrecision"
        onMouseDown={handleMouseDown}
        onMouseMove={handleMouseMove}
        onMouseUp={handleMouseUpOrLeave}
        onMouseLeave={handleMouseUpOrLeave}
        onWheel={handleWheel}
      >
        <defs>
          <linearGradient id="grad-edge-line" x1="0" y1="0" x2="1" y2="0">
            <stop offset="0%" stopColor="rgba(226, 232, 240, 0.6)" />
            <stop offset="100%" stopColor="rgba(241, 245, 249, 0.4)" />
          </linearGradient>
          <pattern id="dotGridVisible" width="36" height="36" patternUnits="userSpaceOnUse">
            <circle cx="18" cy="18" r="1.5" fill="#475569" opacity="0.15" />
          </pattern>
        </defs>

        <rect x="0" y="0" width="1000" height="1000" fill="url(#dotGridVisible)" />

        <g transform={`translate(${pan.x}, ${pan.y})`}>

          {/* Edges */}
          {graphEdges.map((e, i) => {
            const aIdx = graphNodes.findIndex((n) => n.id === e.from);
            const bIdx = graphNodes.findIndex((n) => n.id === e.to);
            if (aIdx < 0 || bIdx < 0) return null;
            const ax = float(aIdx, "x") * 10;
            const ay = float(aIdx, "y") * 10;
            const bx = float(bIdx, "x") * 10;
            const by = float(bIdx, "y") * 10;

            const active = !focus || (connected.has(e.from) && connected.has(e.to));
            const maxRisk: GraphNode["risk"] =
              graphNodes[aIdx].risk === "high" || graphNodes[bIdx].risk === "high"
                ? "high"
                : graphNodes[aIdx].risk === "medium" || graphNodes[bIdx].risk === "medium"
                  ? "medium"
                  : "low";

            const stroke = active ? RISK_COLORS[maxRisk].solid : "url(#grad-edge-line)";

            return (
              <g key={i} opacity={active ? 1 : 0.15} style={{ transition: "opacity 200ms" }}>
                <line
                  x1={ax} y1={ay} x2={bx} y2={by}
                  stroke={stroke}
                  strokeOpacity={active ? 0.75 : 0.5}
                  strokeWidth={active ? 2.5 : 1.5}
                  strokeLinecap="round"
                />
              </g>
            );
          })}

          {/* Nodes */}
          {graphNodes.map((n, i) => {
            const active = !focus || connected.has(n.id);
            const isSelected = n.id === selectedId;
            const nx = float(i, "x") * 10;
            const ny = float(i, "y") * 10;

            const circleDiameter = n.radius * 2.8;
            const wrapperWidth = 180;
            const wrapperHeight = 180;
            const targetStyleColor = RISK_COLORS[n.risk].solid;

            return (
              <g
                key={n.id}
                className="graph-node-container"
                opacity={active ? 1 : 0.25}
                style={{ transition: "opacity 200ms" }}
              >
                <foreignObject
                  x={nx - wrapperWidth / 2}
                  y={ny - wrapperHeight / 2}
                  width={wrapperWidth}
                  height={wrapperHeight}
                >
                  <div className="w-full h-full flex flex-col items-center justify-center">
                    <div
                      onClick={(e) => { e.stopPropagation(); onSelect(n.id); }}
                      onMouseEnter={() => setHover(n.id)}
                      onMouseLeave={() => setHover(null)}
                      style={{
                        width: `${circleDiameter}px`,
                        height: `${circleDiameter}px`,
                        borderColor: isSelected ? targetStyleColor : "#334155",
                        borderWidth: isSelected ? "3px" : "1.5px",
                        boxShadow: isSelected
                          ? `0 0 0 5px ${targetStyleColor}25, 0 6px 20px rgba(15, 23, 42, 0.4)`
                          : undefined,
                      }}
                      className={`graph-node relative rounded-full cursor-pointer ${isSelected ? "scale-105" : ""}`}
                    >
                      <div className="relative z-10 flex items-center justify-center w-full h-full px-2">
                        <span className="text-[11px] font-bold text-white tracking-tight leading-tight text-center">
                          {n.label}
                        </span>
                      </div>
                    </div>
                  </div>
                </foreignObject>
              </g>
            );
          })}
        </g>
      </svg>
    </div>
  );
}