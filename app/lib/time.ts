// The API sends UTC times without a "Z" ("2026-10-07T07:11:00"), which the browser would read as local time.
// Treat any time without a zone as UTC so it shows in the viewer's own time zone.
export function parseUtc(iso: string): Date {
  return new Date(/(Z|[+-]\d\d:?\d\d)$/.test(iso) ? iso : `${iso}Z`);
}

// "Today, 12:45 PM", "Yesterday, 9:10 AM" or "5 Oct, 4:02 PM" in the viewer's time zone.
export function whenLabel(iso: string): string {
  const d = parseUtc(iso);
  const clock = d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  const days = Math.round((new Date().setHours(0, 0, 0, 0) - new Date(d).setHours(0, 0, 0, 0)) / 86400000);
  if (days === 0) return `Today, ${clock}`;
  if (days === 1) return `Yesterday, ${clock}`;
  return `${d.toLocaleDateString([], { day: "numeric", month: "short" })}, ${clock}`;
}
