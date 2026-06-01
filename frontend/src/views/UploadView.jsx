import { useState } from "react";
import { Clapperboard, AlertCircle, ChevronDown } from "lucide-react";
import DropZone from "../components/DropZone";
import { uploadVideo } from "../api";
import { MODELS } from "../App";

const PIPELINE_STEPS = [
  { key: "summarize", label: "Summarize" },
  { key: "topic", label: "Topic extraction" },
  { key: "frame_caption", label: "Frame captioning" },
  { key: "frame_reconcile", label: "Frame reconciliation" },
];

export default function UploadView({ onUploaded, pipelineModels, setPipelineModels }) {
  const [file, setFile] = useState(null);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState(null);
  const [showAdvanced, setShowAdvanced] = useState(false);

  async function handleSubmit(e) {
    e.preventDefault();
    if (!file) return;
    setUploading(true);
    setError(null);
    try {
      const data = await uploadVideo(file, pipelineModels);
      onUploaded(data.job_id);
    } catch (err) {
      setError(err.message ?? "Upload failed. Please try again.");
      setUploading(false);
    }
  }

  return (
    <div className="min-h-screen bg-gray-50 flex flex-col items-center justify-center px-4">
      <div className="w-full max-w-lg bg-white rounded-2xl shadow-sm border border-gray-200 p-8">
        <div className="flex items-center gap-3 mb-8">
          <Clapperboard className="text-violet-600" size={28} />
          <h1 className="text-xl font-semibold text-gray-900">Video Assistant</h1>
        </div>

        <form onSubmit={handleSubmit} className="space-y-5">
          <DropZone onFile={setFile} onError={setError} />

          {/* Advanced settings */}
          <div className="border border-gray-200 rounded-lg overflow-hidden">
            <button
              type="button"
              onClick={() => setShowAdvanced((v) => !v)}
              className="w-full flex items-center justify-between px-4 py-2.5 text-sm text-gray-600 hover:bg-gray-50 transition-colors"
            >
              <span>Advanced settings</span>
              <ChevronDown
                size={16}
                className={`transition-transform ${showAdvanced ? "rotate-180" : ""}`}
              />
            </button>
            {showAdvanced && (
              <div className="border-t border-gray-200 px-4 py-3 space-y-3 bg-gray-50">
                {PIPELINE_STEPS.map(({ key, label }) => (
                  <div key={key} className="flex items-center justify-between gap-4">
                    <label className="text-xs text-gray-600 w-40">{label}</label>
                    <select
                      value={pipelineModels[key]}
                      onChange={(e) =>
                        setPipelineModels((prev) => ({ ...prev, [key]: e.target.value }))
                      }
                      className="text-xs border border-gray-300 rounded-md px-2 py-1.5 bg-white focus:outline-none focus:ring-2 focus:ring-violet-500"
                    >
                      {MODELS.map((m) => (
                        <option key={m} value={m}>
                          {m}
                        </option>
                      ))}
                    </select>
                  </div>
                ))}
              </div>
            )}
          </div>

          {error && (
            <div className="flex items-start gap-2 text-sm text-red-600 bg-red-50 border border-red-200 rounded-lg px-3 py-2.5">
              <AlertCircle size={16} className="shrink-0 mt-0.5" />
              <span>{error}</span>
            </div>
          )}

          <button
            type="submit"
            disabled={!file || uploading}
            className="w-full bg-violet-600 text-white rounded-lg px-4 py-3 text-sm font-medium hover:bg-violet-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            {uploading ? "Uploading…" : "Upload & Analyze"}
          </button>
        </form>
      </div>
    </div>
  );
}
