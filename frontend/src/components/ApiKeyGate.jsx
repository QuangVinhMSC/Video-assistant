import { useState } from "react";
import { KeyRound } from "lucide-react";

export default function ApiKeyGate({ onSave }) {
  const [key, setKey] = useState("");

  function handleSubmit(e) {
    e.preventDefault();
    if (!key.trim()) return;
    localStorage.setItem("api_key", key.trim());
    onSave(key.trim());
  }

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
      <div className="bg-white rounded-2xl shadow-xl p-8 w-full max-w-sm mx-4">
        <div className="flex items-center gap-3 mb-6">
          <KeyRound className="text-violet-600" size={24} />
          <h2 className="text-lg font-semibold text-gray-900">API Key Required</h2>
        </div>
        <form onSubmit={handleSubmit} className="space-y-4">
          <input
            type="password"
            value={key}
            onChange={(e) => setKey(e.target.value)}
            placeholder="Enter your API key"
            className="w-full border border-gray-300 rounded-lg px-4 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-violet-500"
            autoFocus
          />
          <button
            type="submit"
            disabled={!key.trim()}
            className="w-full bg-violet-600 text-white rounded-lg px-4 py-2.5 text-sm font-medium hover:bg-violet-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            Continue
          </button>
        </form>
      </div>
    </div>
  );
}
