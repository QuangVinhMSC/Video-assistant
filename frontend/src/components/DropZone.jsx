import { useState, useRef } from "react";
import { UploadCloud, FileVideo, X } from "lucide-react";

const ACCEPTED_TYPES = ["video/mp4", "video/x-matroska", "video/quicktime", "video/webm", "video/x-msvideo"];
const ACCEPTED_EXT = [".mp4", ".mkv", ".mov", ".webm", ".avi"];
const MAX_BYTES = 500 * 1024 * 1024;

function formatBytes(bytes) {
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export default function DropZone({ onFile, onError }) {
  const [dragging, setDragging] = useState(false);
  const [file, setFile] = useState(null);
  const inputRef = useRef();

  function validate(f) {
    const ext = f.name.toLowerCase().slice(f.name.lastIndexOf("."));
    if (!ACCEPTED_TYPES.includes(f.type) && !ACCEPTED_EXT.includes(ext)) {
      onError("Unsupported file type. Use MP4, MKV, MOV, WEBM, or AVI.");
      return false;
    }
    if (f.size > MAX_BYTES) {
      onError(`File too large (${formatBytes(f.size)}). Maximum is 500 MB.`);
      return false;
    }
    return true;
  }

  function pick(f) {
    if (!f) return;
    if (!validate(f)) return;
    setFile(f);
    onFile(f);
    onError(null);
  }

  function onDrop(e) {
    e.preventDefault();
    setDragging(false);
    pick(e.dataTransfer.files[0]);
  }

  function clear(e) {
    e.stopPropagation();
    setFile(null);
    onFile(null);
    inputRef.current.value = "";
  }

  return (
    <div
      onClick={() => !file && inputRef.current.click()}
      onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
      onDragLeave={() => setDragging(false)}
      onDrop={onDrop}
      className={`
        relative border-2 border-dashed rounded-2xl p-10 text-center transition-all cursor-pointer select-none
        ${dragging ? "border-violet-500 bg-violet-50" : "border-gray-300 hover:border-violet-400 hover:bg-gray-50"}
        ${file ? "cursor-default" : ""}
      `}
    >
      <input
        ref={inputRef}
        type="file"
        accept={ACCEPTED_EXT.join(",")}
        className="hidden"
        onChange={(e) => pick(e.target.files[0])}
      />

      {file ? (
        <div className="flex items-center justify-center gap-3">
          <FileVideo className="text-violet-600 shrink-0" size={28} />
          <div className="text-left">
            <p className="text-sm font-medium text-gray-900 truncate max-w-xs">{file.name}</p>
            <p className="text-xs text-gray-500">{formatBytes(file.size)}</p>
          </div>
          <button onClick={clear} className="ml-2 text-gray-400 hover:text-gray-600 transition-colors">
            <X size={18} />
          </button>
        </div>
      ) : (
        <div className="space-y-3">
          <UploadCloud className="mx-auto text-gray-400" size={40} />
          <div>
            <p className="text-sm font-medium text-gray-700">
              Drag & drop your video here, or <span className="text-violet-600">browse</span>
            </p>
            <p className="text-xs text-gray-400 mt-1">MP4 · MKV · MOV · WEBM · AVI · Max 500 MB</p>
          </div>
        </div>
      )}
    </div>
  );
}
