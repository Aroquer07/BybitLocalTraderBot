/** Converte horários UTC do backend para o offset configurado (ex: -3 = Brasília). */

export function utcOffsetLabel(hours: number): string {
  if (hours === 0) return "UTC";
  const sign = hours > 0 ? "+" : "";
  return `UTC${sign}${hours}`;
}

/** Timestamp ms (UTC) → segundos para lightweight-charts com offset visual. */
export function toChartTime(ms: number, utcOffsetHours: number): number {
  const offsetMs = utcOffsetHours * 60 * 60 * 1000;
  return Math.floor((ms + offsetMs) / 1000);
}

/** ISO / rejected_at → string no fuso configurado (mesma base do gráfico). */
export function formatDisplayTime(iso: string, utcOffsetHours: number): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const shifted = d.getTime() + utcOffsetHours * 3600 * 1000;
  const text = new Date(shifted).toLocaleString("pt-BR", {
    timeZone: "UTC",
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
  return `${text} (${utcOffsetLabel(utcOffsetHours)})`;
}

export const DEFAULT_UTC_OFFSET_HOURS = -3;

function parseUtcOffset(raw: unknown): number | null {
  if (typeof raw === "number" && !Number.isNaN(raw)) return raw;
  if (typeof raw === "string" && raw.trim() !== "") {
    const n = Number(raw);
    if (!Number.isNaN(n)) return n;
  }
  return null;
}

export function readUtcOffsetHours(
  settings: Record<string, unknown> | null | undefined,
  fallback = DEFAULT_UTC_OFFSET_HOURS,
): number {
  const display = settings?.display as { utc_offset_hours?: unknown } | undefined;
  return parseUtcOffset(display?.utc_offset_hours) ?? fallback;
}
