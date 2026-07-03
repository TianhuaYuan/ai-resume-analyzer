import { useEffect, useState, useRef, useCallback, type FormEvent } from "react";
import { useParams } from "react-router-dom";
import { askQuestionStream, getHistory, type SSEEvent } from "../api/qa";
import { listResumes, type ResumeItem } from "../api/resumes";

interface ChatMessage {
  id: number | string; // number = 已存库；string = 临时 ID
  question: string;
  answer: string;
  sources: string[];
  streaming: boolean;
}

export default function QAPage() {
  const { id } = useParams<{ id: string }>();
  const resumeId = Number(id);

  const [resume, setResume] = useState<ResumeItem | null>(null);
  const [chat, setChat] = useState<ChatMessage[]>([]);
  const [question, setQuestion] = useState("");
  const [asking, setAsking] = useState(false);
  const [error, setError] = useState("");
  const [expandedSource, setExpandedSource] = useState<string | null>(null);
  const chatEndRef = useRef<HTMLDivElement>(null);
  const abortRef = useRef<(() => void) | null>(null);

  useEffect(() => {
    listResumes().then((data) => {
      const r = data.items.find((item) => item.id === resumeId);
      if (r) setResume(r);
    });
    getHistory(resumeId)
      .then((data) =>
        setChat(
          data.items.map((it) => ({
            id: it.id,
            question: it.question,
            answer: it.answer,
            sources: it.sources,
            streaming: false,
          }))
        )
      )
      .catch(() => {});
  }, [resumeId]);

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [chat]);

  // 组件卸载时取消 SSE
  useEffect(() => {
    return () => abortRef.current?.();
  }, []);

  const handleAsk = useCallback(
    (e: FormEvent) => {
      e.preventDefault();
      const q = question.trim();
      if (!q || asking) return;

      setQuestion("");
      setError("");
      setAsking(true);

      const tempId = `streaming-${Date.now()}`;
      const newMsg: ChatMessage = {
        id: tempId,
        question: q,
        answer: "",
        sources: [],
        streaming: true,
      };
      setChat((prev) => [...prev, newMsg]);

      abortRef.current = askQuestionStream(
        resumeId,
        q,
        (event: SSEEvent) => {
          if (event.type === "token" && event.content) {
            setChat((prev) =>
              prev.map((m) =>
                m.id === tempId ? { ...m, answer: m.answer + event.content } : m
              )
            );
          } else if (event.type === "done") {
            setChat((prev) =>
              prev.map((m) =>
                m.id === tempId
                  ? {
                      ...m,
                      id: event.qa_id ?? tempId,
                      sources: event.sources ?? [],
                      streaming: false,
                    }
                  : m
              )
            );
            setAsking(false);
          } else if (event.type === "error") {
            setChat((prev) =>
              prev.map((m) =>
                m.id === tempId
                  ? { ...m, answer: event.message ?? "生成失败", streaming: false }
                  : m
              )
            );
            setAsking(false);
          }
        },
        (err: Error) => {
          setError(err.message);
          setChat((prev) =>
            prev.map((m) =>
              m.id === tempId
                ? { ...m, answer: "生成失败，请重试", streaming: false }
                : m
            )
          );
          setAsking(false);
        }
      );
    },
    [question, asking, resumeId]
  );

  // 取消当前生成
  const handleCancel = () => {
    abortRef.current?.();
    setAsking(false);
    setChat((prev) =>
      prev.map((m) =>
        m.streaming ? { ...m, answer: m.answer || "已取消", streaming: false } : m
      )
    );
  };

  return (
    <div className="max-w-3xl mx-auto px-4 py-6 flex flex-col h-[calc(100vh-57px)]">
      {/* 顶栏 */}
      <div className="mb-4 pb-3 border-b border-gray-100">
        <h2 className="text-lg font-semibold text-gray-900 truncate">
          {resume?.filename ?? "加载中..."}
        </h2>
        <p className="text-xs text-gray-400 mt-0.5">
          {resume ? `${resume.chunk_count} 个分块` : ""}
        </p>
      </div>

      {/* 聊天区 */}
      <div className="flex-1 overflow-y-auto pb-4 space-y-5">
        {chat.length === 0 && (
          <div className="text-center py-12 text-gray-400">
            <p className="text-lg mb-1">开始提问</p>
            <p className="text-sm">
              例如：这份简历的亮点是什么？适合什么岗位？
            </p>
          </div>
        )}

        {chat.map((item) => {
          const msgKey = String(item.id);
          return (
            <div key={msgKey}>
              {/* 用户问题 */}
              <div className="flex justify-end mb-3">
                <div className="max-w-[80%] px-4 py-2.5 bg-blue-600 text-white text-sm rounded-2xl rounded-br-md">
                  {item.question}
                </div>
              </div>

              {/* AI 回答 */}
              <div className="flex justify-start">
                <div className="max-w-[85%]">
                  <div
                    className={`px-4 py-3 text-sm rounded-2xl rounded-bl-md leading-relaxed whitespace-pre-wrap ${
                      item.streaming && !item.answer
                        ? "bg-gray-100 text-gray-400"
                        : "bg-gray-100 text-gray-800"
                    }`}
                  >
                    {item.answer || (item.streaming ? "思考中..." : "")}
                    {item.streaming && (
                      <span className="inline-block w-1.5 h-4 bg-gray-500 ml-0.5 animate-pulse align-middle" />
                    )}
                  </div>

                  {/* 来源引用 */}
                  {!item.streaming && item.sources.length > 0 && (
                    <div className="mt-1.5">
                      <button
                        onClick={() =>
                          setExpandedSource(
                            expandedSource === msgKey ? null : msgKey
                          )
                        }
                        className="text-xs text-gray-400 hover:text-gray-600 transition-colors cursor-pointer"
                      >
                        来源 ({item.sources.length}){" "}
                        {expandedSource === msgKey ? "▲" : "▼"}
                      </button>
                      {expandedSource === msgKey && (
                        <div className="mt-1.5 space-y-1.5">
                          {item.sources.map((src, j) => (
                            <div
                              key={j}
                              className="p-2.5 bg-yellow-50 border border-yellow-100 rounded-lg text-xs text-gray-600"
                            >
                              <span className="text-yellow-600 font-medium mr-2">
                                [{j + 1}]
                              </span>
                              {src.length > 200
                                ? src.slice(0, 200) + "..."
                                : src}
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  )}
                </div>
              </div>
            </div>
          );
        })}

        {/* 错误提示 */}
        {error && (
          <div className="p-3 rounded-lg bg-red-50 border border-red-100 text-red-700 text-sm">
            {error}
          </div>
        )}

        <div ref={chatEndRef} />
      </div>

      {/* 输入框 */}
      <form
        onSubmit={handleAsk}
        className="pt-3 border-t border-gray-100 flex gap-3"
      >
        <input
          type="text"
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          placeholder="输入问题，例如：这份简历的亮点是什么？"
          disabled={asking}
          className="flex-1 px-4 py-2.5 border border-gray-300 rounded-xl text-sm
            focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent
            placeholder:text-gray-400 disabled:bg-gray-50"
        />
        {asking ? (
          <button
            type="button"
            onClick={handleCancel}
            className="px-5 py-2.5 bg-gray-400 text-white text-sm font-medium rounded-xl
              hover:bg-gray-500 transition-colors cursor-pointer shrink-0"
          >
            取消
          </button>
        ) : (
          <button
            type="submit"
            disabled={!question.trim()}
            className="px-5 py-2.5 bg-blue-600 text-white text-sm font-medium rounded-xl
              hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed
              transition-colors cursor-pointer shrink-0"
          >
            发送
          </button>
        )}
      </form>
    </div>
  );
}
