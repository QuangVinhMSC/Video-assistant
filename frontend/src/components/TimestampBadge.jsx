function fmt(secs) {
  const m = Math.floor(secs / 60).toString().padStart(2, "0");
  const s = Math.floor(secs % 60).toString().padStart(2, "0");
  return `${m}:${s}`;
}

export default function TimestampBadge({ start, end }) {
  return (
    <span className="inline-flex items-center gap-1 bg-violet-100 text-violet-700 text-xs font-mono px-2 py-0.5 rounded-full">
      {fmt(start)} → {fmt(end)}
    </span>
  );
}
