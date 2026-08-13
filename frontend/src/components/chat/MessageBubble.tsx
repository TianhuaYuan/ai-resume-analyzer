import { memo, useState, useRef, useEffect, useCallback } from "react";
import { Check, Copy, RefreshCw, ThumbsUp, ThumbsDown, Trash2 } from "lucide-react";
import { formatTimestamp, type ChatMessage } from "./ChatMessage";
import { ROLE_STYLES } from "../roleStyles";
import HighlightedText from "../HighlightedText";
import AgentProcessPanel from "./AgentProcessPanel";
import DiagnosisCard, { isDiagnosisMessage } from "./DiagnosisCard";
import Citations from "./Citations";
import AgentCardRouter from "../AgentCardRouter";
import MarkdownRenderer from "../MarkdownRenderer";

/** 流式光标（AI 回答仍在生成时闪烁提示） */
export function StreamingCursor() {
  return (
    <span className="inline-block w-0.5 h-4 bg-brand ml-0.5 align-middle animate-cursor-blink" />
  );
}

export interface MessageBubbleProps {
  msg: ChatMessage;
  deleting: boolean;
  onDelete: (id: number | string) => void;
  /** current 为当前反馈状态，用于判断点同按钮=取消、点异按钮=切换 */
  onFeedback: (
    id: number | string,
    rating: "positive" | "negative",
    current?: "positive" | "negative" | null
  ) => void;
  /** G2: hover 消息动作栏 — 重新生成（重新发送该消息的问题） */
  onRegenerate: (msg: ChatMessage) => void;
  /** G2: 是否正在等待 AI 回复（流式期间禁用重新生成） */
  asking: boolean;
  /** P4-10: 历史搜索关键词（非空时高亮命中文本） */
  searchTerm?: string;
  /** v2: 是否为最后一条消息（hover 动作栏常显，Open WebUI 降低发现成本） */
  isLast?: boolean;
}

/** G2: 复制文本到剪贴板（Clipboard API + 非安全上下文降级 textarea 方案） */
export async function copyToClipboard(text: string): Promise<void> {
  try {
    await navigator.clipboard.writeText(text);
  } catch {
    // 非安全上下文（如 http 明文）降级：临时 textarea + execCommand
    try {
      const ta = document.createElement("textarea");
      ta.value = text;
      ta.style.position = "fixed";
      ta.style.opacity = "0";
      document.body.appendChild(ta);
      ta.select();
      document.execCommand("copy");
      document.body.removeChild(ta);
    } catch { /* 忽略复制失败 */ }
  }
}

/** 去掉模型偶发生成的行首装饰性 emoji，保留正文中的技术符号和评分内容。 */
export function cleanAssistantText(text: string): string {
  return text.replace(
    /^(\s*(?:(?:#{1,6}|[-*+]|\d+\.|>)\s+)?(?:\*{1,2})?)(?:[\p{Extended_Pictographic}\uFE0F]\s*)+/gmu,
    "$1",
  );
}

const MessageBubble = memo(function MessageBubble({ msg, deleting, onDelete, onFeedback, onRegenerate, asking, searchTerm, isLast = false }: MessageBubbleProps) {
  // 流式消息（id 仍是字符串 tempId）不显示删除按钮和反馈按钮
  const canDelete = !msg.streaming && typeof msg.id === "number";
  const canFeedback = !msg.streaming && typeof msg.id === "number";
  // 失败/中断消息：非流式且 id 仍是临时字符串（未落库）→ 红色提示 + 常显重试
  const isFailed = !msg.streaming && typeof msg.id === "string";
  // G2: 复制动作反馈（"已复制"短暂提示）
  const [copied, setCopied] = useState(false);
  const displayAnswer = cleanAssistantText(msg.answer || "");
  const copyTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => () => {
    if (copyTimerRef.current) clearTimeout(copyTimerRef.current);
  }, []);
  const handleCopy = useCallback(async () => {
    await copyToClipboard(displayAnswer || msg.question || "");
    setCopied(true);
    if (copyTimerRef.current) clearTimeout(copyTimerRef.current);
    copyTimerRef.current = setTimeout(() => setCopied(false), 2000);
  }, [displayAnswer, msg.question]);
  return (
    <div className="group animate-fade-in-up">
      {/* 用户问题（P4-8 角色样式：右对齐 brand 底色） */}
      <div className="flex justify-end mb-4">
        <div className={`max-w-[85%] px-4 py-3 ${ROLE_STYLES.user.bg}
          ${ROLE_STYLES.user.text} text-sm leading-relaxed rounded-input rounded-br-md`}>
          {/* P4-10: 搜索词高亮（历史搜索命中时高亮） */}
          {searchTerm ? (
            <HighlightedText text={msg.question} terms={[searchTerm]} />
          ) : (
            msg.question
          )}
        </div>
      </div>

      {/* AI 回答 */}
      <div className="flex justify-start mb-4">
        <div className="relative max-w-[82%] group/bubble">
          {/* G2: 消息动作栏（hover 气泡出现）— 复制 + 重新生成 */}
          {!msg.streaming && (
            <div className={`absolute -top-2.5 right-2 z-10 flex items-center gap-0.5
              px-1 py-0.5 rounded-action bg-[var(--color-bg)] border border-[var(--color-border)]
              shadow-sm transition-opacity duration-200
              ${isLast ? "opacity-100" : "opacity-0 group-hover/bubble:opacity-100"}`}>
              <button
                onClick={handleCopy}
                aria-label={copied ? "已复制" : "复制内容"}
                title={copied ? "已复制" : "复制内容"}
                className="p-1 rounded text-[var(--color-text-muted)]
                  hover:text-brand hover:bg-brand/10 active:scale-95
                  motion-reduce:active:scale-100 transition-all cursor-pointer"
              >
                {copied
                  ? <Check size={11} strokeWidth={2.25} aria-hidden="true" />
                  : <Copy size={11} aria-hidden="true" />}
              </button>
              <button
                onClick={() => onRegenerate(msg)}
                disabled={asking}
                aria-label="重新生成"
                title={asking ? "等待当前回答完成" : "重新生成回答"}
                className="p-1 rounded text-[var(--color-text-muted)]
                  hover:text-brand hover:bg-brand/10 active:scale-95
                  motion-reduce:active:scale-100 transition-all cursor-pointer
                  disabled:opacity-40 disabled:cursor-not-allowed"
              >
                <RefreshCw size={11} aria-hidden="true" />
              </button>
            </div>
          )}
          <div className={`px-4 py-3.5 rounded-input rounded-bl-md leading-relaxed text-sm
            ${ROLE_STYLES.assistant.bg} ${ROLE_STYLES.assistant.text}`}>
            {/* T18: Agent 推理过程面板（#11: streaming 开始即显示占位，用户立即看到反馈） */}
            {msg.streaming || (msg.agent_steps && msg.agent_steps.length > 0) ? (
              <AgentProcessPanel steps={msg.agent_steps ?? []} streaming={msg.streaming} />
            ) : null}
            {msg.streaming && !msg.answer && !(msg.agent_steps && msg.agent_steps.length > 0) ? (
              /* P1: 打字指示器精化——两粒圆点 pulse + 上浮（1.5s），对齐 Open WebUI */
              <span
                className="inline-flex items-center gap-1 py-0.5 text-[var(--color-text-muted)]"
                role="status"
                aria-label="正在处理"
              >
                <span className="w-1.5 h-1.5 rounded-full bg-current animate-typing-dot" />
                <span className="w-1.5 h-1.5 rounded-full bg-current animate-typing-dot" style={{ animationDelay: "150ms" }} />
              </span>
            ) : !msg.streaming && isDiagnosisMessage(msg) ? (
              /* E1: 简历诊断回答 → 结构化卡片（评分提取失败自动回退纯 markdown） */
              <DiagnosisCard answer={displayAnswer} sources={msg.sources} />
            ) : !msg.streaming && msg.agent_steps && msg.agent_steps.length > 0 ? (
              /* P1-C: 有 Agent 步骤时 → 卡片通用分发（JDMatchReport 等，无匹配则 markdown） */
              <AgentCardRouter steps={msg.agent_steps} answer={displayAnswer} streaming={msg.streaming} />
            ) : msg.streaming ? (
              /* 流式期间纯文本渲染：answer_token 每帧追加，若走 MarkdownRenderer 会
                 每帧全量重新解析完整 markdown（react-markdown 无增量），CPU 密集卡顿。
                 完成后（agent_done）才解析 markdown 一次。 */
              /* P1: 流式期间 token 淡入——answerChunks 每帧追加一段，新段插入时淡入（100ms） */
              <div className="whitespace-pre-wrap break-words">
                {msg.answerChunks && msg.answerChunks.length > 0
                  ? msg.answerChunks.map((chunk, i) => (
                      <span key={i} className="inline animate-fade-in-token">{chunk}</span>
                    ))
                  : displayAnswer}
              </div>
            ) : (
              /* 超长答案折叠：避免 agent_done 后一次性解析/渲染超大 markdown DOM
                 （这是"最后一次渲染慢"的卡点），>3000 字截断 + 展开全文 */
              <MarkdownRenderer maxChars={3000}>
                {displayAnswer}
              </MarkdownRenderer>
            )}
            {msg.streaming && msg.answer && <StreamingCursor />}

            {/* 失败/中断消息：视觉区分 + 常显重试按钮（不依赖 hover） */}
            {isFailed && (
              <div className="mt-2 flex items-center gap-2">
                <span className="text-[10px] px-1.5 py-0.5 rounded bg-danger-soft text-danger border border-danger/30 shrink-0">
                  未完成
                </span>
                <button
                  onClick={() => onRegenerate(msg)}
                  disabled={asking}
                  className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-medium
                    text-brand bg-brand/10 border border-brand/30 hover:brightness-125
                    disabled:opacity-40 disabled:cursor-not-allowed transition-all cursor-pointer"
                  aria-label="重试此问题"
                >
                  <RefreshCw size={10} strokeWidth={2.25} aria-hidden="true" />
                  重试
                </button>
              </div>
            )}
          </div>

          {/* 普通问答来源引用（诊断卡分支内部已含来源，不重复渲染） */}
          {!msg.streaming && !isDiagnosisMessage(msg) && (
            <div className="mt-2">
              <Citations sources={msg.sources} />
            </div>
          )}

          {/* 来源引用 + 反馈 + 删除按钮 */}
          {!msg.streaming && (
            <div className="flex items-start justify-between gap-2">
              <div className="flex-1 min-w-0">
                {msg.created_at && formatTimestamp(msg.created_at) && (
                  <span
                    data-testid="message-timestamp"
                    className="text-[11px] tabular-nums text-[var(--color-text-muted)] mt-1 block"
                  >
                    {formatTimestamp(msg.created_at)}
                  </span>
                )}
                {/* Token 消耗：文本徽标可视化（P4-11 借鉴 Hermes TokenBar 思路） */}
              </div>
              <div className="shrink-0 flex items-center gap-1 mt-2">
                {/* Task 5.1: 质量反馈按钮（点同按钮=取消，点异按钮=切换） */}
                {canFeedback && (
                  <>
                    <button
                      onClick={() => onFeedback(msg.id, "positive", msg.feedback)}
                      aria-label="有帮助"
                      title={msg.feedback === "positive" ? "取消反馈" : "标记为有帮助"}
                      className={`inline-flex items-center gap-0.5 px-1.5 py-1
                        rounded-md text-xs transition-all cursor-pointer
                        ${msg.feedback === "positive"
                          ? "text-brand bg-brand/10"
                          : "text-[var(--color-text-muted)] hover:text-brand hover:bg-brand/10"
                        }`}
                    >
                      <ThumbsUp size={12} fill={msg.feedback === "positive" ? "currentColor" : "none"} aria-hidden="true" />
                    </button>
                    <button
                      onClick={() => onFeedback(msg.id, "negative", msg.feedback)}
                      aria-label="没帮助"
                      title={msg.feedback === "negative" ? "取消反馈" : "标记为没帮助"}
                      className={`inline-flex items-center gap-0.5 px-1.5 py-1
                        rounded-md text-xs transition-all cursor-pointer
                        ${msg.feedback === "negative"
                          ? "text-danger bg-danger/10"
                          : "text-[var(--color-text-muted)] hover:text-danger hover:bg-danger/10"
                        }`}
                    >
                      <ThumbsDown size={12} fill={msg.feedback === "negative" ? "currentColor" : "none"} aria-hidden="true" />
                    </button>
                  </>
                )}
                {canDelete && (
                  <button
                    onClick={() => !deleting && onDelete(msg.id)}
                    disabled={deleting}
                    aria-label="删除该问答"
                    className="inline-flex items-center gap-1 px-1.5 py-1
                      rounded-md text-xs text-[var(--color-text-muted)]
                      hover:text-danger hover:bg-danger/10
                      active:scale-[0.95] motion-reduce:active:scale-100
                      transition-all cursor-pointer
                      opacity-0 group-hover:opacity-100 focus:opacity-100
                      disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    {deleting ? (
                      <span
                        className="inline-block w-3 h-3 rounded-full border-2 border-current border-t-transparent animate-spin"
                        aria-hidden="true"
                      />
                    ) : (
                      <Trash2 size={12} aria-hidden="true" />
                    )}
                    删除
                  </button>
                )}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
});

export default MessageBubble;
