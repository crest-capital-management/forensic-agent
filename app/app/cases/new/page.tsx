"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import Select from "@/components/Select";

const YEARS = ["FY2022", "FY2023", "FY2024", "FY2025", "FY2026"];

export default function NewCase() {
  const router = useRouter();
  const [companies, setCompanies] = useState<{ company_id: number; name: string }[]>([]);
  const [companyId, setCompanyId] = useState<number | "">("");
  const [years, setYears] = useState<string[]>(["FY2025", "FY2026"]);
  const [name, setName] = useState("");
  const [reason, setReason] = useState("");
  const [exposure, setExposure] = useState("");
  const [portfolio, setPortfolio] = useState(false);
  const [err, setErr] = useState("");

  useEffect(() => {
    api<typeof companies>("/companies")
      .then((c) => {
        setCompanies(c);
        const wanted = Number(new URLSearchParams(window.location.search).get("company"));   // from the Home row menu
        setCompanyId(c.some((x) => x.company_id === wanted) ? wanted : c.length ? c[0].company_id : "");
      })
      .catch((e) => setErr(e.message));
  }, []);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setErr("");
    try {
      const r = await api<{ id: number }>("/cases", {
        method: "POST",
        body: { company_id: companyId, name: name || null, years, reason, exposure_note: exposure || null, is_portfolio_company: portfolio },
      });
      router.push(`/cases/${r.id}`);
    } catch (e: any) {
      setErr(e.message);
    }
  }

  return (
    <form onSubmit={submit} className="card form">
      <h1>New case</h1>
      <label>Company
        <Select searchable value={companyId} onChange={(v) => setCompanyId(Number(v))} options={companies.map((c) => ({ value: c.company_id, label: c.name }))} />
      </label>
      <label>Case name (optional)
        <input type="text" value={name} maxLength={120} onChange={(e) => setName(e.target.value)} placeholder="For example: TCS receivables review, FY2025 to FY2026" />
      </label>
      <fieldset>
        <legend>Years to review</legend>
        {YEARS.map((y) => (
          <label key={y} className="inline">
            <input
              type="checkbox"
              checked={years.includes(y)}
              onChange={(e) => setYears(e.target.checked ? [...years, y] : years.filter((x) => x !== y))}
            />
            {y}
          </label>
        ))}
      </fieldset>
      <label>Reason for opening this case
        <textarea value={reason} onChange={(e) => setReason(e.target.value)} rows={3} required />
      </label>
      <label>Exposure note (optional)
        <textarea value={exposure} onChange={(e) => setExposure(e.target.value)} rows={2} />
      </label>
      <label className="inline">
        <input type="checkbox" checked={portfolio} onChange={(e) => setPortfolio(e.target.checked)} />
        This is a portfolio company (escalating a flag will need the adviser&apos;s approval)
      </label>
      {err && <p className="error">{err}</p>}
      <button className="btn primary" type="submit">Open case</button>
    </form>
  );
}
