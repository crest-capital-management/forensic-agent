"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import Loader from "@/components/Loader";

export default function AnalysisIndex() {
  const router = useRouter();
  const [rows, setRows] = useState<any[] | null>(null);
  const [err, setErr] = useState("");

  useEffect(() => {
    api<any[]>("/home").then((r) => {
      if (r.length === 1) router.replace(`/analysis/${r[0].company_id}`);   // only one company: go straight to it
      else setRows(r);
    }).catch((e) => setErr(e.message));
  }, [router]);

  if (err) return <p className="error">{err}</p>;
  if (!rows) return <Loader label="Opening the analysis" />;
  return (
    <>
      <h1>Analysis</h1>
      <p className="muted">Choose a company to see its measures side by side across the years.</p>
      <div className="stack">
        {rows.map((r) => (
          <Link key={r.company_id} href={`/analysis/${r.company_id}`} className="card link">
            <strong>{r.name}</strong> <span className="muted">{r.symbol}</span>
          </Link>
        ))}
        {rows.length === 0 && <p className="muted">No companies yet.</p>}
      </div>
    </>
  );
}
