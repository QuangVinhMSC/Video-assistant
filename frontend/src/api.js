const BASE = import.meta.env.VITE_API_URL ?? "";

function headers() {
  return {
    "X-API-Key": localStorage.getItem("api_key") ?? "",
  };
}

async function handleResponse(res) {
  if (res.ok) return res.json();
  let message = `HTTP ${res.status}`;
  try {
    const body = await res.json();
    message = body.detail ?? body.message ?? message;
  } catch {}
  throw { status: res.status, message };
}

export async function uploadVideo(file, pipelineModels = {}) {
  const form = new FormData();
  form.append("file", file);
  form.append("model_summarize", pipelineModels.summarize ?? "gpt-5.5");
  form.append("model_topic", pipelineModels.topic ?? "gpt-4o-mini");
  form.append("model_frame_caption", pipelineModels.frame_caption ?? "gpt-4o");
  form.append("model_frame_reconcile", pipelineModels.frame_reconcile ?? "gpt-4o-mini");
  const res = await fetch(`${BASE}/upload`, {
    method: "POST",
    headers: headers(),
    body: form,
  });
  return handleResponse(res);
}

export async function getStatus(jobId) {
  const res = await fetch(`${BASE}/status/${jobId}`, { headers: headers() });
  return handleResponse(res);
}

export async function askQuestion(jobId, question, qaModel = "gpt-4o-mini") {
  const res = await fetch(`${BASE}/ask/${jobId}`, {
    method: "POST",
    headers: { ...headers(), "Content-Type": "application/json" },
    body: JSON.stringify({ question, qa_model: qaModel }),
  });
  return handleResponse(res);
}
