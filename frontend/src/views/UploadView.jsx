import { useState } from "react";
import { Clapperboard, AlertCircle } from "lucide-react";
import DropZone from "../components/DropZone";
import { uploadVideo } from "../api";

export default function UploadView({ onUploaded }) {
  const [file, setFile] = useState(null);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState(null);

  async function handleSubmit(e) {
    e.preventDefault();
    if (!file) return;
    setUploading(true);
    setError(null);
    try {
      const data = await uploadVideo(file);
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
