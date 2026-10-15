"use client";

import * as Dropdown from "@radix-ui/react-dropdown-menu";
import * as Tooltip from "@radix-ui/react-tooltip";
import {
  ColumnDef, flexRender, getCoreRowModel, getFilteredRowModel, getSortedRowModel, SortingState, useReactTable,
} from "@tanstack/react-table";
import { ArrowDown, ArrowUp, ArrowUpDown, X } from "lucide-react";
import { motion } from "framer-motion";
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import { api } from "@/lib/api";
import { parseUtc } from "@/lib/time";
import Loader from "@/components/Loader";
import { IconDots, IconSearch, IconStar } from "@/components/icons";

type Row = {
  company_id: number; type: string; symbol: string; name: string; sector: string | null; supported_status: string | null;
  flags: { high: number; medium: number; low: number }; flags_total: number; last_screen: string | null; draft: boolean;
  cases: number; latest_case_id: number | null; is_portfolio: boolean; in_watchlist: boolean;
};

function Tip({ text, children }: { text: string; children: React.ReactNode }) {
  return (
    <Tooltip.Root delayDuration={150}>
      <Tooltip.Trigger asChild>{children}</Tooltip.Trigger>
      <Tooltip.Portal><Tooltip.Content className="tip" sideOffset={6}>{text}<Tooltip.Arrow className="tip-arrow" /></Tooltip.Content></Tooltip.Portal>
    </Tooltip.Root>
  );
}

export default function Home() {
  const [rows, setRows] = useState<Row[] | null>(null);
  const [filter, setFilter] = useState<"all" | "portfolio" | "watchlist">("all");
  const [search, setSearch] = useState("");
  const [sorting, setSorting] = useState<SortingState>([{ id: "name", desc: false }]);
  const [err, setErr] = useState("");

  const load = () => api<Row[]>("/home").then(setRows).catch((e) => setErr(e.message));
  useEffect(() => { load(); }, []);

  async function toggleWatch(r: Row) {
    try {
      await api("/watchlist", { method: "POST", body: { company_id: r.company_id, watch: !r.in_watchlist } });
      toast.success(r.in_watchlist ? `${r.name} removed from your watchlist` : `${r.name} added to your watchlist`);
      load();
    } catch (e: any) {
      toast.error(e.message);
    }
  }

  const data = useMemo(
    () => (rows || []).filter((r) => filter === "all" || (filter === "portfolio" ? r.is_portfolio : r.in_watchlist)),
    [rows, filter],
  );

  const columns = useMemo<ColumnDef<Row>[]>(() => [
    {
      id: "actions", header: "", enableSorting: false,
      cell: ({ row }) => {
        const r = row.original;
        return (
          <Dropdown.Root>
            <Dropdown.Trigger asChild><button className="icon-btn" aria-label={`Actions for ${r.name}`}><IconDots size={18} /></button></Dropdown.Trigger>
            <Dropdown.Portal>
              <Dropdown.Content className="menu" align="start" sideOffset={4}>
                {r.latest_case_id && <Dropdown.Item asChild className="menu-item"><Link href={`/cases/${r.latest_case_id}`}>Open latest case</Link></Dropdown.Item>}
                <Dropdown.Item asChild className="menu-item"><Link href={`/analysis/${r.company_id}`}>Multi-Annual Forensic Analysis</Link></Dropdown.Item>
                <Dropdown.Item asChild className="menu-item"><Link href={`/analysis/${r.company_id}?view=mscore`}>Detailed M-Score Breakdown</Link></Dropdown.Item>
                <Dropdown.Item asChild className="menu-item"><Link href={`/cases/new?company=${r.company_id}`}>New case for {r.symbol}</Link></Dropdown.Item>
                <Dropdown.Separator className="menu-sep" />
                <Dropdown.Item className="menu-item" onSelect={() => toggleWatch(r)}>
                  {r.in_watchlist ? "Remove from watchlist" : "Add to watchlist"}
                </Dropdown.Item>
              </Dropdown.Content>
            </Dropdown.Portal>
          </Dropdown.Root>
        );
      },
    },
    { accessorKey: "type", header: "Type", enableSorting: false },
    {
      accessorKey: "symbol", header: "Symbol",
      cell: ({ row }) => (
        <span className="sym">
          {row.original.symbol}
          {row.original.in_watchlist && <Tip text="On your watchlist"><span className="star"><IconStar size={12} /></span></Tip>}
        </span>
      ),
    },
    {
      accessorKey: "name", header: "Name",
      cell: ({ row }) => {
        const r = row.original;
        return (<>
          {r.latest_case_id ? <Link href={`/cases/${r.latest_case_id}`}>{r.name}</Link> : r.name}
          {r.is_portfolio && <span className="badge" style={{ marginLeft: 8 }}>portfolio</span>}
        </>);
      },
    },
    { accessorKey: "sector", header: "Sector", enableSorting: false, cell: ({ getValue }) => <span className="muted">{(getValue() as string) || "—"}</span> },
    {
      id: "flags", header: "Flags H / M / L", accessorFn: (r) => r.flags_total,
      cell: ({ row }) => {
        const { flags, flags_total } = row.original;
        return flags_total === 0 ? <span className="muted">no flags</span> : (
          <span className="flagcounts"><b className="c-high">{flags.high}</b> / <b className="c-medium">{flags.medium}</b> / <b className="c-low">{flags.low}</b></span>
        );
      },
    },
    {
      id: "last", header: "Last screen", accessorFn: (r) => r.last_screen || "",
      cell: ({ row }) => <span className="muted">{row.original.last_screen ? parseUtc(row.original.last_screen).toLocaleDateString() : "never"}</span>,
    },
    {
      id: "config", header: "Limits", enableSorting: false,
      cell: ({ row }) => !row.original.last_screen ? "—" : row.original.draft
        ? <Tip text="The limits behind these flags are not yet approved by the forensic lead"><span className="badge tone-wait">draft</span></Tip>
        : <span className="badge tone-accept">approved</span>,
    },
    { accessorKey: "cases", header: "Cases", enableSorting: false },
  ], []); // eslint-disable-line react-hooks/exhaustive-deps

  const table = useReactTable({
    data, columns, state: { sorting, globalFilter: search }, onSortingChange: setSorting, onGlobalFilterChange: setSearch,
    globalFilterFn: (row, _id, term) => [row.original.name, row.original.symbol, row.original.sector || ""].some((x) => x.toLowerCase().includes(String(term).toLowerCase())),
    getCoreRowModel: getCoreRowModel(), getSortedRowModel: getSortedRowModel(), getFilteredRowModel: getFilteredRowModel(),
  });

  const empty = filter === "all" ? "No companies match." : filter === "portfolio"
    ? "No portfolio companies yet: open a case and tick “portfolio company”."
    : "Your watchlist is empty: use the ⋯ menu on a company to add it.";

  return (
    <Tooltip.Provider>
      <div className="search">
        <IconSearch size={18} />
        <input type="text" value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search a company, symbol or sector" aria-label="Search" />
        {search && <button type="button" className="search-clear" aria-label="Clear search" onClick={() => setSearch("")}><X size={15} /></button>}
      </div>

      <div className="filterbar">
        <div className="segmented sliding" role="tablist" aria-label="Filter companies">
          {([["all", "All companies"], ["portfolio", "Portfolio"], ["watchlist", "Watchlist"]] as const).map(([k, label]) => (
            <button key={k} role="tab" aria-selected={filter === k} className={filter === k ? "on" : ""} onClick={() => setFilter(k)}>
              {filter === k && <motion.span layoutId="filter-pill" className="pill" transition={{ type: "spring", stiffness: 500, damping: 38 }} />}
              <span className="pill-label">{label}</span>
            </button>
          ))}
        </div>
        <Link href="/cases/new" className="btn primary newcase">New case</Link>
      </div>

      {err && <p className="error">{err}. Is the API running? (python -m crest_forensic.review.api)</p>}
      {rows === null && !err && <Loader label="Loading companies" />}

      {rows && (
        <div className="tablewrap">
          <table className="assets">
            <thead>
              {table.getHeaderGroups().map((hg) => (
                <tr key={hg.id}>
                  {hg.headers.map((h) => {
                    const sorted = h.column.getIsSorted();
                    return (
                      <th key={h.id} className={h.column.getCanSort() ? "sortable" : ""} onClick={h.column.getToggleSortingHandler()}
                        aria-sort={sorted === "asc" ? "ascending" : sorted === "desc" ? "descending" : undefined}>
                        {flexRender(h.column.columnDef.header, h.getContext())}
                        {h.column.getCanSort() && (
                          <span className="sortmark">{sorted === "asc" ? <ArrowUp size={12} /> : sorted === "desc" ? <ArrowDown size={12} /> : <ArrowUpDown size={12} />}</span>
                        )}
                      </th>
                    );
                  })}
                </tr>
              ))}
            </thead>
            <motion.tbody key={filter} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.25, ease: "easeOut" }}>
              {table.getRowModel().rows.map((row) => (
                <tr key={row.id}>
                  {row.getVisibleCells().map((c) => <td key={c.id}>{flexRender(c.column.columnDef.cell, c.getContext())}</td>)}
                </tr>
              ))}
              {table.getRowModel().rows.length === 0 && (
                <tr><td colSpan={columns.length} className="muted" style={{ textAlign: "center", padding: 28 }}>{empty}</td></tr>
              )}
            </motion.tbody>
          </table>
        </div>
      )}
      <p className="muted small" style={{ marginTop: 12 }}>
        Flag counts come from the newest screen of each basis. They are leads for review, not findings.
      </p>
    </Tooltip.Provider>
  );
}
