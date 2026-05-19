import { useState } from "react";
import ApiKeyGate from "./components/ApiKeyGate";
import UploadView from "./views/UploadView";
import ProcessingView from "./views/ProcessingView";
import ChatView from "./views/ChatView";

export default function App() {
  const [apiKey, setApiKey] = useState(() => localStorage.getItem("api_key"));
  const [view, setView] = useState("upload");
  const [jobId, setJobId] = useState(null);
  const [jobData, setJobData] = useState(null);

  function handleUploaded(id) {
    setJobId(id);
    setView("processing");
  }

  function handleReady(data) {
    setJobData(data);
    setView("chat");
  }

  function handleReset() {
    setJobId(null);
    setJobData(null);
    setView("upload");
  }

  return (
    <>
      {!apiKey && <ApiKeyGate onSave={setApiKey} />}
      {view === "upload" && <UploadView onUploaded={handleUploaded} />}
      {view === "processing" && <ProcessingView jobId={jobId} onReady={handleReady} />}
      {view === "chat" && <ChatView jobId={jobId} jobData={jobData} onReset={handleReset} />}
    </>
  );
}
