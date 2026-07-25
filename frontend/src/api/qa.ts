import { api } from "./client";
import { refreshToken, notifySessionExpired } from "./client";

export interface AnswerResponse {
  id: number;
  question: string;
  answer: string;
  sources: string[];
  created_at: string;
}

export interface SSEEvent {
  /** 事件去重用的唯一 id（N5）。后端未下发时为 undefined，此时不去重。 */
  id?: string | number;
  type: "status" | "token" | "done" | "error" | "reset";
  message?: string;
  content?: string;
  answer?: string;
  sources?: string[];
  qa_id?: number;
}

/**
 * N5：判断某个 SSE 事件是否应被丢弃（已出现过相同 id）。
 * 纯函数，便于单测。后端若未下发 id 则永远返回 false（不去重）。
 */
export function shouldSkipEvent(seen: Set<string>, event: SSEEvent): boolean {
  if (event.id == null) return false;
  const key = String(event.id);
  if (seen.has(key)) return true;
  seen.add(key);
  return false;
}

/**
 * SSE 流式问答。返回 abort 函数用于取消请求。
 * onEvent 在每个 SSE 事件时调用；onError 在出错时调用；
 * onDone 在流"无论正常结束还是异常"后都会调用（取消除外），用于兜底重置 UI 状态（C2）。
 */
export function askQuestionStream(
  resume_id: number,
  question: string,
  onEvent: (event: SSEEvent) => void,
  onError: (err: Error) => void,
  onDone?: () => void,
): () => void {
  const abort = new AbortController();
  const seenIds = new Set<string>();
  let aborted = false;

  const buildHeaders = (): Record<string, string> => ({
    "Content-Type": "application/json",
    ...(localStorage.getItem("access_token")
      ? { Authorization: `Bearer ${localStorage.getItem("access_token")}` }
      : {}),
  });

  const body = JSON.stringify({ resume_id, question });

  (async () => {
    try {
      let res = await fetch("/api/v1/qa/ask/stream", {
        method: "POST",
        headers: buildHeaders(),
        body,
        signal: abort.signal,
      });

      // H10：流式接口原本不走 client.request，不会自动刷新 token。
      // 这里补上：401 先刷新再重试；刷新失败则弹过期提示。
      if (res.status === 401) {
        const ok = await refreshToken();
        if (!ok) {
          notifySessionExpired();
          throw new Error("登录已过期");
        }
        res = await fetch("/api/v1/qa/ask/stream", {
          method: "POST",
          headers: buildHeaders(),
          body,
          signal: abort.signal,
        });
      }

      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: "请求失败" }));
        throw new Error((err as { detail?: string }).detail || "请求失败");
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
            if (shouldSkipEvent(seenIds, data)) continue; // N5 去重
            onEvent(data);
          } catch {
            // 跳过解析失败的行
          }
        }
      }
    } catch (err) {
      if (err instanceof DOMException && err.name === "AbortError") {
        aborted = true;
        return;
      }
      onError(err instanceof Error ? err : new Error("流式请求失败"));
    } finally {
      // C2：流结束（正常或异常）必兜底，确保 asking 状态一定被复位，
      // 否则网络中途断开没收到 done 事件时输入框会卡死在"发送中"。
      // 用户主动取消（abort）由调用方自己复位，这里跳过。
      if (!aborted) onDone?.();
    }
  })();

  return () => abort.abort();
}

export async function getHistory(
  resume_id: number,
  limit = 20,
  offset = 0,
  keyword?: string
) {
  const params = new URLSearchParams();
  params.set("limit", String(limit));
  params.set("offset", String(offset));
  if (keyword && keyword.trim()) {
    params.set("keyword", keyword.trim());
  }
  return api.get(
    `/api/v1/qa/history/${resume_id}?${params.toString()}`
  ) as Promise<{ items: AnswerResponse[]; total: number }>;
}

export interface QADeleteResult {
  deleted_count: number;
}

/** 清空指定简历的所有问答历史，返回被删除的记录数。 */
export async function clearHistory(resume_id: number): Promise<QADeleteResult> {
  return api.delete(
    `/api/v1/qa/history/${resume_id}`
  ) as Promise<QADeleteResult>;
}

/** 删单条问答记录。后端返回 204，前端不解析 body。 */
export async function deleteQa(qa_id: number): Promise<void> {
  await api.delete(`/api/v1/qa/${qa_id}`);
}
