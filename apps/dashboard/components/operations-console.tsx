"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { Activity, CheckCircle2, CircleAlert, Clock3, Database, RefreshCw, Search, ShieldCheck, Users } from "lucide-react";

type RecordValue = Record<string, unknown>;
type Tab = "overview" | "rounds" | "clients" | "updates" | "artifacts" | "blockchain";

const tabs: { id: Tab; label: string }[] = [
  { id: "overview", label: "Overview" },
  { id: "rounds", label: "Rounds" },
  { id: "clients", label: "Clients" },
  { id: "updates", label: "Updates" },
  { id: "artifacts", label: "Artifacts" },
  { id: "blockchain", label: "Blockchain" },
];

function text(value: unknown, fallback = "—") {
  return value === null || value === undefined || value === "" ? fallback : String(value);
}

function date(value: unknown) {
  if (!value) return "—";
  const parsed = new Date(String(value));
  return Number.isNaN(parsed.getTime()) ? text(value) : parsed.toLocaleString();
}

function statusClass(status: unknown) {
  const normalized = String(status || "").toUpperCase();
  if (["ACTIVE", "ONLINE", "VERIFIED", "AGGREGATED", "CONFIRMED"].includes(normalized)) return "status status-good";
  if (["FAILED", "REJECTED", "OFFLINE"].includes(normalized)) return "status status-bad";
  return "status status-warn";
}

function Table({ columns, rows, onSelect }: {
  columns: { key: string; label: string; mono?: boolean }[];
  rows: RecordValue[];
  onSelect: (row: RecordValue) => void;
}) {
  if (!rows.length) {
    return <div className="empty-state"><Database size={22} /><strong>No records match this view</strong><span>Try clearing the filter or refresh when the next event arrives.</span></div>;
  }
  return (
    <div className="table-wrap">
      <table>
        <thead><tr>{columns.map((column) => <th key={column.key}>{column.label}</th>)}</tr></thead>
        <tbody>
          {rows.map((row, index) => (
            <tr key={String(row.id || row.update_id || row.entity_id || index)} onClick={() => onSelect(row)}>
              {columns.map((column) => {
                const value = row[column.key];
                const isStatus = column.key === "status" || column.key === "is_active";
                return <td key={column.key} className={column.mono ? "mono" : ""}>{isStatus ? <span className={statusClass(column.key === "is_active" ? (value ? "ACTIVE" : "OFFLINE") : value)}>{column.key === "is_active" ? (value ? "ONLINE" : "OFFLINE") : text(value)}</span> : text(value)}</td>;
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Metric({ label, value, detail, icon: Icon, tone }: { label: string; value: string | number; detail: string; icon: typeof Activity; tone: string }) {
  return <div className={`metric-card ${tone}`}><div className="metric-icon"><Icon size={18} /></div><div><span>{label}</span><strong>{value}</strong><small>{detail}</small></div></div>;
}

export default function OperationsConsole() {
  const [tab, setTab] = useState<Tab>("overview");
  const [federations, setFederations] = useState<RecordValue[]>([]);
  const [selectedFederation, setSelectedFederation] = useState("");
  const [data, setData] = useState({ clients: [], rounds: [], updates: [], artifacts: [], transactions: [] } as Record<string, RecordValue[]>);
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState("ALL");
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);
  const [selected, setSelected] = useState<RecordValue | null>(null);

  const load = useCallback(async (silent = false) => {
    if (!silent) setLoading(true);
    setError("");
    try {
      const get = async (endpoint: string) => {
        const response = await fetch(`/api/dashboard${endpoint}`, { cache: "no-store" });
        if (!response.ok) throw new Error(`Dashboard API returned ${response.status}`);
        const payload = await response.json();
        return payload.data || [];
      };
      const nextFederations = await get("/federations/?limit=100");
      const federationId = selectedFederation || String(nextFederations[0]?.id || "");
      const [clients, rounds, updates, artifacts, transactions] = federationId
        ? await Promise.all([
            get(`/clients/federation/${federationId}`),
            get(`/rounds/federation/${federationId}`),
            get(`/updates/federation/${federationId}`),
            get(`/artifacts/federation/${federationId}`),
            get("/blockchain/transactions?limit=100"),
          ])
        : [[], [], [], [], []];
      setFederations(nextFederations);
      if (!selectedFederation && federationId) setSelectedFederation(federationId);
      setData({ clients, rounds, updates, artifacts, transactions });
      setLastUpdated(new Date());
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Unable to load dashboard data");
    } finally {
      setLoading(false);
    }
  }, [selectedFederation]);

  useEffect(() => { void load(); }, [load]);
  useEffect(() => {
    const interval = window.setInterval(() => void load(true), 15000);
    return () => window.clearInterval(interval);
  }, [load]);
  useEffect(() => { setPage(1); }, [query, status, tab, selectedFederation]);

  const activeFederation = federations.find((item) => String(item.id) === selectedFederation);
  const allRecords = data[tab === "overview" ? "updates" : tab === "blockchain" ? "transactions" : tab] || [];
  const filtered = useMemo(() => allRecords.filter((row) => {
    const matchesQuery = !query || JSON.stringify(row).toLowerCase().includes(query.toLowerCase());
    const rowStatus = row.status === undefined ? (row.is_active ? "ONLINE" : "OFFLINE") : String(row.status);
    return matchesQuery && (status === "ALL" || rowStatus === status);
  }), [allRecords, query, status]);
  const visible = filtered.slice((page - 1) * 8, page * 8);
  const totalUpdates = data.updates.length;
  const verified = data.updates.filter((row) => ["VERIFIED", "AGGREGATED"].includes(String(row.status))).length;
  const activeClients = data.clients.filter((row) => row.is_active).length;
  const confirmed = data.transactions.filter((row) => row.status === "CONFIRMED").length;
  const activeRound = data.rounds.find((row) => row.status === "ACTIVE");

  return <div className="console-shell">
    <header className="console-header">
      <div><p className="eyebrow">TRUSTFL / OPERATIONS</p><h1>Federation control room</h1><p className="muted">Monitor training, verification, artifacts, and ledger convergence from one persisted view.</p></div>
      <div className="header-actions"><span className="live-pill"><span /> Live · 15s</span><button className="button button-secondary" onClick={() => void load()} disabled={loading}><RefreshCw size={15} className={loading ? "spin" : ""} /> Refresh</button></div>
    </header>
    <div className="toolbar"><label htmlFor="federation">Federation</label><select id="federation" value={selectedFederation} onChange={(event) => setSelectedFederation(event.target.value)}><option value="">No federation selected</option>{federations.map((item) => <option key={String(item.id)} value={String(item.id)}>{text(item.name, String(item.id))}</option>)}</select><span className="toolbar-meta">{activeFederation ? `${text(activeFederation.status)} · ${text(activeFederation.id)}` : "Waiting for federation data"}{lastUpdated ? ` · Updated ${lastUpdated.toLocaleTimeString()}` : ""}</span></div>
    {error && <div className="error-banner"><CircleAlert size={18} /><span>{error}</span><button onClick={() => void load()}>Retry</button></div>}
    {!loading && !federations.length && !error && <div className="empty-state page-empty"><Database size={28} /><strong>No federation has been initialized</strong><span>Create a federation through the API, then refresh this console.</span></div>}
    <section className="metrics-grid">
      <Metric label="Federation health" value={activeFederation ? text(activeFederation.status) : "WAITING"} detail={activeFederation ? "Control plane status" : "No active federation"} icon={Activity} tone="tone-blue" />
      <Metric label="Active round" value={activeRound ? `#${text(activeRound.round_number)}` : "—"} detail={activeRound ? text(activeRound.status) : "No round in progress"} icon={Clock3} tone="tone-purple" />
      <Metric label="Online clients" value={`${activeClients}/${data.clients.length}`} detail="Heartbeat availability" icon={Users} tone="tone-green" />
      <Metric label="Verified updates" value={`${verified}/${totalUpdates}`} detail="Verified or aggregated" icon={ShieldCheck} tone="tone-amber" />
      <Metric label="Ledger confirmed" value={`${confirmed}/${data.transactions.length}`} detail="Blockchain transactions" icon={CheckCircle2} tone="tone-cyan" />
    </section>
    <nav className="tabs">{tabs.map((item) => <button key={item.id} className={tab === item.id ? "tab active" : "tab"} onClick={() => setTab(item.id)}>{item.label}<span>{item.id === "overview" ? data.updates.length : data[item.id]?.length || 0}</span></button>)}</nav>
    <section className="panel">
      <div className="panel-heading"><div><h2>{tabs.find((item) => item.id === tab)?.label}</h2><p className="muted">{filtered.length} records · click a row for details</p></div>{tab !== "overview" && <div className="filters"><div className="search"><Search size={15} /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search records" /></div><select value={status} onChange={(event) => setStatus(event.target.value)}><option value="ALL">All statuses</option>{["ACTIVE", "ONLINE", "VERIFIED", "AGGREGATED", "CONFIRMED", "PENDING", "REJECTED", "FAILED", "OFFLINE"].map((item) => <option key={item}>{item}</option>)}</select></div>}</div>
      {loading ? <div className="loading-state"><RefreshCw className="spin" size={20} /> Loading control-plane data…</div> : tab === "overview" ? <div className="overview-grid"><div><h3>Recent updates</h3><Table columns={[{ key: "id", label: "Update", mono: true }, { key: "client_id", label: "Client", mono: true }, { key: "status", label: "Verification" }, { key: "artifact_hash", label: "Artifact hash", mono: true }]} rows={data.updates.slice(0, 8)} onSelect={setSelected} /></div><div><h3>Aggregation pipeline</h3><div className="pipeline"><div className="pipeline-step"><span className="pipeline-dot done" />Submitted <strong>{totalUpdates}</strong></div><div className="pipeline-step"><span className="pipeline-dot done" />Verified <strong>{verified}</strong></div><div className="pipeline-step"><span className="pipeline-dot" />Aggregated <strong>{data.updates.filter((row) => row.status === "AGGREGATED").length}</strong></div><div className="pipeline-step"><span className="pipeline-dot" />Artifacts <strong>{data.artifacts.length}</strong></div></div></div></div> : <><Table columns={tab === "rounds" ? [{ key: "id", label: "Round", mono: true }, { key: "round_number", label: "Number" }, { key: "status", label: "Status" }, { key: "model_version", label: "Model" }] : tab === "clients" ? [{ key: "id", label: "Client", mono: true }, { key: "is_active", label: "Heartbeat" }, { key: "last_seen_at", label: "Last seen" }, { key: "registered_at", label: "Registered" }] : tab === "updates" ? [{ key: "id", label: "Update", mono: true }, { key: "client_id", label: "Client", mono: true }, { key: "status", label: "Status" }, { key: "num_examples", label: "Examples" }, { key: "artifact_hash", label: "Artifact hash", mono: true }] : tab === "artifacts" ? [{ key: "id", label: "Artifact", mono: true }, { key: "model_version", label: "Model" }, { key: "sha256_hash", label: "SHA-256", mono: true }, { key: "uri", label: "CID / URI", mono: true }] : [{ key: "contract_name", label: "Contract" }, { key: "function_name", label: "Function" }, { key: "status", label: "Status" }, { key: "tx_hash", label: "Transaction", mono: true }, { key: "created_at", label: "Created" }]} rows={visible} onSelect={setSelected} /><div className="pagination"><span>Page {page} of {Math.max(1, Math.ceil(filtered.length / 8))}</span><div><button className="button button-secondary" disabled={page === 1} onClick={() => setPage((current) => current - 1)}>Previous</button><button className="button button-secondary" disabled={page * 8 >= filtered.length} onClick={() => setPage((current) => current + 1)}>Next</button></div></div></>}
    </section>
    {selected && <div className="detail-drawer"><div className="drawer-heading"><div><p className="eyebrow">RECORD DETAIL</p><h2>{text(selected.id || selected.update_id || selected.tx_hash)}</h2></div><button className="drawer-close" onClick={() => setSelected(null)}>×</button></div><dl>{Object.entries(selected).map(([key, value]) => <div key={key}><dt>{key.replaceAll("_", " ")}</dt><dd className={key.includes("hash") || key.includes("uri") || key === "id" ? "mono" : ""}>{typeof value === "object" ? JSON.stringify(value) : text(value)}</dd></div>)}</dl></div>}
  </div>;
}
