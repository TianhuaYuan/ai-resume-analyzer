import { useEffect, useState, useRef, type FormEvent } from "react";
import { useParams } from "react-router-dom";
import { askQuestion, getHistory, type AnswerResponse } from "../api/qa";
import { listResumes, type ResumeItem } from "../api/resumes";

export default function QAPage() {
  const { id } = useParams<{ id: string }>();
  const resumeId = Number(id);

  const [resume, setResume] = useState<ResumeItem | null>(null);
  const [chat, setChat] = useState<AnswerResponse[]>([]);
  const [question, setQuestion] = useState("");
  const [asking, setAsking] = useState(false);
  const [error, setError] = useState("");
  const [expandedSource, setExpandedSource] = useState<number | null>(null);
  const chatEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    // 拿到简历文件名
    listResumes().then((data) => {
      const r = data.items.find((item) => item.id === resumeId);
      if (r) setResume(r);
    });
    // 加载历史问答
    getHistory(resumeId)
      .then((data) => setChat(data.items))
      .catch(() => {});
  }, [resumeId]);

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [chat]);

  const handleAsk = async (e: FormEvent) => {
    e.preventDefault();
    const q = question.trim();
    if (!q || asking) return;

    setQuestion("");
    setError("");
    setAsking(true);
    try {
      const answer = await askQuestion(resumeId, q);
      setChat((prev) => [...prev, answer]);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "提问失败");
    } finally {
      setAsking(false);
    }
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

        {chat.map((item, i) => (
          <div key={item.id || i}>
            {/* 用户问题 */}
            <div className="flex justify-end mb-3">
              <div className="max-w-[80%] px-4 py-2.5 bg-blue-600 text-white text-sm rounded-2xl rounded-br-md">
                {item.question}
              </div>
            </div>

            {/* AI 回答 */}
            <div className="flex justify-start">
              <div className="max-w-[85%]">
                <div className="px-4 py-3 bg-gray-100 text-gray-800 text-sm rounded-2xl rounded-bl-md leading-relaxed whitespace-pre-wrap">
                  {item.answer}
                </div>

                {/* 来源引用 */}
                {item.sources && item.sources.length > 0 && (
                  <div className="mt-1.5">
                    <button
                      onClick={() =>
                        setExpandedSource(
                          expandedSource === i ? null : i
                        )
                      }
                      className="text-xs text-gray-400 hover:text-gray-600 transition-colors cursor-pointer"
                    >
                      来源 ({item.sources.length}){" "}
                      {expandedSource === i ? "▲" : "▼"}
                    </button>
                    {expandedSource === i && (
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
        ))}

        {/* 错误提示 */}
        {error && (
          <div className="p-3 rounded-lg bg-red-50 border border-red-100 text-red-700 text-sm">
            {error}
          </div>
        )}

        {/* 思考中 */}
        {asking && (
          <div className="flex justify-start">
            <div className="px-5 py-3 bg-gray-100 text-gray-500 text-sm rounded-2xl rounded-bl-md">
              <span className="inline-flex gap-1">
                <span className="w-1.5 h-1.5 bg-gray-400 rounded-full animate-bounce" />
                <span className="w-1.5 h-1.5 bg-gray-400 rounded-full animate-bounce [animation-delay:0.15s]" />
                <span className="w-1.5 h-1.5 bg-gray-400 rounded-full animate-bounce [animation-delay:0.3s]" />
              </span>
            </div>
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
        <button
          type="submit"
          disabled={asking || !question.trim()}
          className="px-5 py-2.5 bg-blue-600 text-white text-sm font-medium rounded-xl
            hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed
            transition-colors cursor-pointer shrink-0"
        >
          {asking ? "思考中" : "发送"}
        </button>
      </form>
    </div>
  );
}
