import { api } from "./client";

export interface AnswerResponse {
  id: number;
  question: string;
  answer: string;
  sources: string[];
  created_at: string;
}

export interface SSEEvent {
  type: "status" | "token" | "done" | "error";
  message?: string;
  content?: string;
  answer?: string;
  sources?: string[];
  qa_id?: number;
}

export async function askQuestion(
  resume_id: number,
  question: string
): Promise<AnswerResponse> {
  return api.post("/api/qa/ask", { resume_id, question }) as Promise<AnswerResponse>;
}

/**
 * SSE 流式问答。返回 abort 函数用于取消请求。
 * onEvent 在每个 SSE 事件时调用，onDone 在流结束时调用。
 */
export function askQuestionStream(
  resume_id: number,
  question: string,
  onEvent: (event: SSEEvent) => void,
  onError: (err: Error) => void,
): () => void {
  const abort = new AbortController();
  const token = localStorage.getItem("access_token");

  (async () => {
    try {
      const res = await fetch("/api/qa/ask/stream", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({ resume_id, question }),
        signal: abort.signal,
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: "请求失败" }));
        throw new Error(err.detail || "请求失败");
      }

      const reader = res.body?.getReader();
      if (!reader) throw new Error("无法读取响应流");

      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        // SSE 事件以 \n\n 分隔
        const parts = buffer.split("\n\n");
        buffer = parts.pop() || "";

        for (const part of parts) {
          const line = part.trim();
          if (!line.startsWith("data: ")) continue;
          try {
            const data: SSEEvent = JSON.parse(line.slice(6));
            onEvent(data);
          } catch {
            // 跳过解析失败的行
          }
        }
      }
    } catch (err) {
      if (err instanceof DOMException && err.name === "AbortError") return;
      onError(err instanceof Error ? err : new Error("流式请求失败"));
    }
  })();

  return () => abort.abort();
}

export async function getHistory(
  resume_id: number,
  limit = 20,
  offset = 0
) {
  return api.get(
    `/api/qa/history/${resume_id}?limit=${limit}&offset=${offset}`
  ) as Promise<{ items: AnswerResponse[]; total: number }>;
}
