export function Sev({ v }: { v: string }) {
  return <span className={`badge sev-${v}`}>{v}</span>;
}

export function Tag({ children, tone = "plain" }: { children: React.ReactNode; tone?: string }) {
  return <span className={`badge tone-${tone}`}>{children}</span>;
}

export function ReviewTag({ review }: { review: { decision: string; carried_from?: { run_id: number } | null } | null }) {
  if (!review) return <Tag>unreviewed</Tag>;
  const word = review.decision === "accept" ? "accepted" : "rejected";
  const tone = review.decision === "accept" ? "accept" : "reject";
  if (review.carried_from)
    return <span title={`Decided on the identical flag in run ${review.carried_from.run_id}. Open the flag to confirm or change it.`}><Tag tone={tone}>{word} · earlier run</Tag></span>;
  return <Tag tone={tone}>{word}</Tag>;
}

export function EscTag({ esc }: { esc: { state: string } | null }) {
  if (!esc) return null;
  return esc.state === "escalated" ? <Tag tone="esc">escalated</Tag> : <Tag tone="wait">awaiting adviser</Tag>;
}
