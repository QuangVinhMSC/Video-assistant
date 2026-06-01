import { useState } from "react";
import ApiKeyGate from "./components/ApiKeyGate";
import UploadView from "./views/UploadView";
import ProcessingView from "./views/ProcessingView";
import ChatView from "./views/ChatView";

export const MODELS = ["gpt-4o-mini", "gpt-4o", "gpt-5.5"];

export default function App() {
  const [apiKey, setApiKey] = useState(() => localStorage.getItem("api_key"));
  const [view, setView] = useState("upload");
  const [jobId, setJobId] = useState(null);
  const [jobData, setJobData] = useState(null);
  const [pipelineModels, setPipelineModels] = useState({
    summarize: "gpt-5.5",
    topic: "gpt-4o-mini",
    frame_caption: "gpt-4o",
    frame_reconcile: "gpt-4o-mini",
  });
  const [qaModel, setQaModel] = useState("gpt-4o-mini");

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
      {view === "upload" && (
        <UploadView
          onUploaded={handleUploaded}
          pipelineModels={pipelineModels}
          setPipelineModels={setPipelineModels}
        />
      )}
      {view === "processing" && <ProcessingView jobId={jobId} onReady={handleReady} />}
      {view === "chat" && (
        <ChatView
          jobId={jobId}
          jobData={jobData}
          onReset={handleReset}
          qaModel={qaModel}
          setQaModel={setQaModel}
        />
      )}
    </>
  );
}
