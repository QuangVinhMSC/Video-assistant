import { CheckCircle, Circle, Loader } from "lucide-react";

const STEPS = [
  { key: "uploaded",           label: "Uploaded" },
  { key: "extracting_audio",   label: "Extracting audio" },
  { key: "extracting_frames",  label: "Extracting frames" },
  { key: "running_ocr",        label: "Running OCR" },
  { key: "captioning_frames",  label: "Captioning frames" },
  { key: "transcribing",       label: "Transcribing" },
  { key: "summarizing",        label: "Summarizing" },
  { key: "chunking",           label: "Chunking" },
  { key: "embedding",          label: "Embedding" },
  { key: "ready",              label: "Ready" },
];

const ORDER = STEPS.map((s) => s.key);

function fmtDuration(ms) {
  const s = Math.round(ms / 1000);
  if (s < 60) return `${s}s`;
  return `${Math.floor(s / 60)}m ${s % 60}s`;
}

export default function StatusTimeline({ currentStatus, stepTimings }) {
  const currentIdx = ORDER.indexOf(currentStatus);

  return (
    <ol className="space-y-2">
      {STEPS.map((step, i) => {
        const done = i < currentIdx || currentStatus === "ready";
        const active = i === currentIdx && currentStatus !== "ready";
        const duration = stepTimings?.[step.key];

        return (
          <li key={step.key} className="flex items-center gap-3">
            {done ? (
              <CheckCircle size={18} className="text-violet-600 shrink-0" />
            ) : active ? (
              <Loader size={18} className="text-violet-500 animate-spin shrink-0" />
            ) : (
              <Circle size={18} className="text-gray-300 shrink-0" />
            )}
            <span
              className={`text-sm flex-1 ${
                done ? "text-gray-700" : active ? "text-violet-600 font-medium" : "text-gray-400"
              }`}
            >
              {step.label}
            </span>
            {duration != null && (
              <span className="text-xs text-gray-400 tabular-nums">
                {fmtDuration(duration)}
              </span>
            )}
          </li>
        );
      })}
    </ol>
  );
}
