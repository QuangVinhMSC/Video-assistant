import { useState, useEffect, useRef } from "react";
import { AlertCircle, RefreshCw } from "lucide-react";
import ProgressBar from "../components/ProgressBar";
import StatusTimeline from "../components/StatusTimeline";
import { getStatus } from "../api";

const PROGRESS = {
  uploaded: 5,
  extracting_audio: 20,
  transcribing: 40,
  summarizing: 60,
  chunking: 75,
  embedding: 90,
  ready: 100,
};

function formatElapsed(secs) {
  if (secs < 60) return `${secs}s`;
  return `${Math.floor(secs / 60)}m ${secs % 60}s`;
}

export default function ProcessingView({ jobId, onReady }) {
  const [status, setStatus] = useState("uploaded");
  const [error, setError] = useState(null);
  const [elapsed, setElapsed] = useState(0);
  const intervalRef = useRef(null);
  const timerRef = useRef(null);

  useEffect(() => {
    timerRef.current = setInterval(() => setElapsed((e) => e + 1), 1000);

    async function poll() {
      try {
        const data = await getStatus(jobId);
        setStatus(data.status);
        if (data.status === "ready") {
          stop();
          onReady(data);
        } else if (data.status === "failed") {
          stop();
          setError(data.error ?? "Processing failed at step: " + data.step);
        }
      } catch (err) {
        setError(err.message ?? "Could not reach server.");
        stop();
      }
    }

    poll();
    intervalRef.current = setInterval(poll, 3000);

    return () => stop();
  }, [jobId]);

  function stop() {
    clearInterval(intervalRef.current);
    clearInterval(timerRef.current);
  }

  function retry() {
    window.location.reload();
  }

  const progress = PROGRESS[status] ?? 5;

  return (
    <div className="min-h-screen bg-gray-50 flex flex-col items-center justify-center px-4">
      <div className="w-full max-w-md bg-white rounded-2xl shadow-sm border border-gray-200 p-8 space-y-6">
        <div>
          <h2 className="text-lg font-semibold text-gray-900 mb-1">Processing your video…</h2>
          <p className="text-sm text-gray-500">Elapsed: {formatElapsed(elapsed)}</p>
        </div>

        <div className="space-y-2">
          <div className="flex justify-between text-xs text-gray-500">
            <span>Progress</span>
            <span>{progress}%</span>
          </div>
          <ProgressBar percent={progress} />
        </div>

        <StatusTimeline currentStatus={status} />

        {error && (
          <div className="space-y-3">
            <div className="flex items-start gap-2 text-sm text-red-600 bg-red-50 border border-red-200 rounded-lg px-3 py-2.5">
              <AlertCircle size={16} className="shrink-0 mt-0.5" />
              <span>{error}</span>
            </div>
            <button
              onClick={retry}
              className="flex items-center gap-2 text-sm text-violet-600 hover:text-violet-800 transition-colors"
            >
              <RefreshCw size={14} />
              Start over
            </button>
          </div>
        )}

        <p className="text-xs text-gray-400">Job ID: <span className="font-mono">{jobId}</span></p>
      </div>
    </div>
  );
}
