import { useState, useRef, useEffect } from "react";
import { ArrowLeft, Send, AlertCircle, Loader } from "lucide-react";
import MessageBubble from "../components/MessageBubble";
import { askQuestion } from "../api";
import { MODELS } from "../App";

export default function ChatView({ jobId, jobData, onReset, qaModel, setQaModel }) {
  const [messages, setMessages] = useState([
    {
      role: "assistant",
      content: "Ready! Ask me anything about this video.",
    },
  ]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const bottomRef = useRef(null);
  const textareaRef = useRef(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, loading]);

  async function handleSend() {
    const question = input.trim();
    if (!question || loading) return;

    setInput("");
    setError(null);
    setMessages((prev) => [...prev, { role: "user", content: question }]);
    setLoading(true);

    try {
      const data = await askQuestion(jobId, question, qaModel);
      const content = {
        answer: data.answer ?? "No answer returned.",
        based_on_video: data.based_on_video ?? [],
        expert_explanation: data.expert_explanation ?? [],
        relevant_timestamps: data.relevant_timestamps ?? [],
        search_note: data.search_note ?? null,
      };
      setMessages((prev) => [...prev, { role: "assistant", content }]);
    } catch (err) {
      const msg =
        err.status === 429
          ? "Too many requests — wait a moment and try again."
          : err.message ?? "Something went wrong. Please try again.";
      setError(msg);
      setMessages((prev) => prev.slice(0, -1));
      setInput(question);
    } finally {
      setLoading(false);
    }
  }

  function handleKeyDown(e) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  }

  const parentTopic = jobData?.parent_topic ?? jobData?.topics?.parent_topic;
  const mainTopic = jobData?.main_topic ?? jobData?.topics?.main_topic;

  return (
    <div className="min-h-screen bg-gray-50 flex flex-col">
      {/* Header */}
      <div className="bg-white border-b border-gray-200 px-4 py-3 flex items-center gap-4">
        <button
          onClick={onReset}
          className="flex items-center gap-1.5 text-sm text-gray-500 hover:text-violet-600 transition-colors"
        >
          <ArrowLeft size={16} />
          Upload new video
        </button>
        {mainTopic && (
          <div className="flex items-center gap-2 text-sm">
            <span className="font-medium text-gray-900">{mainTopic}</span>
            {parentTopic && (
              <span className="text-xs bg-violet-100 text-violet-700 px-2 py-0.5 rounded-full">
                {parentTopic}
              </span>
            )}
          </div>
        )}
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto px-4 py-6 space-y-4 max-w-3xl w-full mx-auto">
        {messages.map((msg, i) => (
          <MessageBubble key={i} role={msg.role} content={msg.content} />
        ))}
        {loading && (
          <div className="flex justify-start">
            <div className="bg-gray-100 rounded-2xl rounded-tl-sm px-4 py-3">
              <Loader size={16} className="text-violet-500 animate-spin" />
            </div>
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      {/* Input */}
      <div className="bg-white border-t border-gray-200 px-4 py-3">
        <div className="max-w-3xl mx-auto space-y-2">
          {error && (
            <div className="flex items-start gap-2 text-xs text-red-600 bg-red-50 border border-red-200 rounded-lg px-3 py-2">
              <AlertCircle size={14} className="shrink-0 mt-0.5" />
              <span>{error}</span>
            </div>
          )}
          <div className="flex gap-2">
            <select
              value={qaModel}
              onChange={(e) => setQaModel(e.target.value)}
              className="text-xs border border-gray-300 rounded-xl px-2 py-2 bg-white focus:outline-none focus:ring-2 focus:ring-violet-500 self-end"
            >
              {MODELS.map((m) => (
                <option key={m} value={m}>{m}</option>
              ))}
            </select>
            <textarea
              ref={textareaRef}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              disabled={loading}
              rows={1}
              placeholder="Ask a question… (Enter to send, Shift+Enter for newline)"
              className="flex-1 border border-gray-300 rounded-xl px-4 py-2.5 text-sm resize-none focus:outline-none focus:ring-2 focus:ring-violet-500 disabled:opacity-50"
              style={{ minHeight: "44px", maxHeight: "160px" }}
              onInput={(e) => {
                e.target.style.height = "auto";
                e.target.style.height = Math.min(e.target.scrollHeight, 160) + "px";
              }}
            />
            <button
              onClick={handleSend}
              disabled={!input.trim() || loading}
              className="bg-violet-600 text-white rounded-xl px-4 hover:bg-violet-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            >
              <Send size={16} />
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
