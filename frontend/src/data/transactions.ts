export type TxRisk = "low" | "medium" | "high";

export interface TxSummary {
  id: string;
  timestamp: string;
  amount: string;
  amountValue: number;
  merchant: string;
  country: string;
  riskScore: number;
  risk: TxRisk;
}

export const TRANSACTIONS: TxSummary[] = [
  { id: "TX-9F2A-7C81-44E0", timestamp: "Jun 13, 2026 · 14:02 UTC", amount: "$12,480.00", amountValue: 12480, merchant: "Helios Logistics", country: "AE", riskScore: 87, risk: "high" },
  { id: "TX-7B1C-3D94-22A1", timestamp: "Jun 13, 2026 · 13:48 UTC", amount: "$842.50", amountValue: 842.5, merchant: "Northwind Goods", country: "US", riskScore: 22, risk: "low" },
  { id: "TX-5E08-91FA-7C12", timestamp: "Jun 13, 2026 · 13:31 UTC", amount: "$3,210.00", amountValue: 3210, merchant: "Aurora Travel", country: "DE", riskScore: 58, risk: "medium" },
  { id: "TX-2A77-08BC-9E45", timestamp: "Jun 13, 2026 · 13:10 UTC", amount: "$48.99", amountValue: 48.99, merchant: "ByteStream Media", country: "GB", riskScore: 14, risk: "low" },
  { id: "TX-6C44-AAB2-1F09", timestamp: "Jun 13, 2026 · 12:58 UTC", amount: "$9,990.00", amountValue: 9990, merchant: "Cresta Holdings", country: "CY", riskScore: 79, risk: "high" },
  { id: "TX-1D33-77E5-B028", timestamp: "Jun 13, 2026 · 12:42 UTC", amount: "$120.00", amountValue: 120, merchant: "GreenLeaf Market", country: "CA", riskScore: 31, risk: "low" },
  { id: "TX-8F90-2C11-5570", timestamp: "Jun 13, 2026 · 12:19 UTC", amount: "$4,500.00", amountValue: 4500, merchant: "Volt Mobility", country: "NL", riskScore: 64, risk: "medium" },
  { id: "TX-3B21-66DA-0C8E", timestamp: "Jun 13, 2026 · 11:55 UTC", amount: "$275.20", amountValue: 275.2, merchant: "Café Lumen", country: "FR", riskScore: 18, risk: "low" },
  { id: "TX-A012-44FF-9911", timestamp: "Jun 13, 2026 · 11:33 UTC", amount: "$18,750.00", amountValue: 18750, merchant: "Onyx Capital", country: "SG", riskScore: 91, risk: "high" },
  { id: "TX-4E5D-1188-22B0", timestamp: "Jun 13, 2026 · 11:02 UTC", amount: "$640.00", amountValue: 640, merchant: "Pulse Fitness", country: "AU", riskScore: 42, risk: "medium" },
];