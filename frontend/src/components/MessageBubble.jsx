import ReactMarkdown from "react-markdown";
import TimestampBadge from "./TimestampBadge";

function AssistantContent({ content }) {
  if (typeof content === "string") {
    return (
      <div className="prose prose-sm prose-violet max-w-none">
        <ReactMarkdown>{content}</ReactMarkdown>
      </div>
    );
  }

  const { answer, based_on_video, expert_explanation, relevant_timestamps, search_note } = content;

  return (
    <div className="space-y-3 text-sm text-gray-800">
      <div className="prose prose-sm prose-violet max-w-none">
        <ReactMarkdown>{answer}</ReactMarkdown>
      </div>

      {based_on_video?.length > 0 && (
        <div>
          <p className="font-semibold text-gray-700 mb-1">Based on the video</p>
          <ul className="list-disc list-inside space-y-0.5 text-gray-600">
            {based_on_video.map((item, i) => <li key={i}>{item}</li>)}
          </ul>
        </div>
      )}

      {expert_explanation?.length > 0 && (
        <div>
          <p className="font-semibold text-gray-700 mb-1">Expert explanation</p>
          <ul className="list-disc list-inside space-y-0.5 text-gray-600">
            {expert_explanation.map((item, i) => <li key={i}>{item}</li>)}
          </ul>
        </div>
      )}

      {relevant_timestamps?.length > 0 && (
        <div>
          <p className="font-semibold text-gray-700 mb-1">Relevant timestamps</p>
          <div className="flex flex-wrap gap-1.5">
            {relevant_timestamps.map((ts, i) => {
              if (typeof ts === "string") {
                // Backend format: "02:05-03:00"
                const [a, b] = ts.split("-");
                const toSecs = (t) => {
                  const [m, s] = t.trim().split(":").map(Number);
                  return m * 60 + s;
                };
                return <TimestampBadge key={i} start={toSecs(a)} end={toSecs(b)} />;
              }
              return <TimestampBadge key={i} start={ts.start} end={ts.end} />;
            })}
          </div>
        </div>
      )}

      {search_note && (
        <p className="text-xs text-gray-400 italic border-t border-gray-100 pt-2">
          {search_note}
        </p>
      )}
    </div>
  );
}

export default function MessageBubble({ role, content }) {
  if (role === "user") {
    return (
      <div className="flex justify-end">
        <div className="bg-violet-600 text-white rounded-2xl rounded-tr-sm px-4 py-2.5 max-w-lg text-sm">
          {content}
        </div>
      </div>
    );
  }

  return (
    <div className="flex justify-start">
      <div className="bg-gray-100 rounded-2xl rounded-tl-sm px-4 py-3 max-w-2xl">
        <AssistantContent content={content} />
      </div>
    </div>
  );
}
