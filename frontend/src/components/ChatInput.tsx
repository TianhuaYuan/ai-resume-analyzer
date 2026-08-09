import { useRef, useState, type FormEvent } from "react";
import {
  FileText,
  Translate,
  Briefcase,
  Microphone,
  MapTrifold,
  Paperclip,
  PaperPlaneRight,
  Stop,
} from "@phosphor-icons/react";

/**
 * ChatInput — Agent 聊天页输入区（独立组件，本地管理输入状态）。
 *
 * 性能优化：输入框的 value 状态在组件内部维护，每次按键只重渲染本组件，
 * 不再触发 QAPage 整页重渲染。提交/快捷标签/附件通过回调通知父组件。
 */

interface ChatInputProps {
  /** 是否正在等待 AI 回复（asking 时输入仍可用，走 inject 补充通道） */
  asking: boolean;
  /** 是否正在上传附件 */
  uploading: boolean;
  /** 是否禁用输入（无简历时） */
  disabled?: boolean;
  /** 发送文本（父组件处理真实发送） */
  onSend: (text: string) => void;
  /** P1-2: asking 期间补充消息 → 注入当前回合（而非排队新回合） */
  onInject?: (text: string) => void;
  /** 取消当前流式回复 */
  onCancel: () => void;
  /** 点击快捷标签发送预置问题 */
  onQuickTag: (question: string) => void;
  /** 选择附件文件 */
  onFile: (file: File) => void;
}

// 输入框底部工具栏快捷标签
const QUICK_TAGS = [
  { icon: FileText, label: "简历诊断", question: "请全面诊断这份简历的优点和不足" },
  { icon: Translate, label: "简历翻译", question: "请将这份简历翻译为英文" },
  { icon: Briefcase, label: "校招推荐", question: "请实时搜索最近的校招和社招岗位机会" },
  { icon: Microphone, label: "面试指导", question: "请根据这份简历模拟一场面试" },
  { icon: MapTrifold, label: "职业规划", question: "请帮我分析我的职业发展方向" },
] as const;

export default function ChatInput({
  asking,
  uploading,
  disabled = false,
  onSend,
  onInject,
  onCancel,
  onQuickTag,
  onFile,
}: ChatInputProps) {
  const [value, setValue] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    setValue(e.target.value);
    // 自动调整高度，最大 128px（约 5-6 行）
    const el = e.currentTarget;
    el.style.height = "auto";
    el.style.height = Math.min(el.scrollHeight, 128) + "px";
  };

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault();
    const q = value.trim();
    if (!q) return;
    // P1-2: asking 期间 → 注入当前回合（用户随时补充信息），而非排队新回合
    if (asking) {
      if (onInject) {
        onInject(q);
        setValue("");
        if (textareaRef.current) {
          textareaRef.current.style.height = "auto";
        }
      }
      return;
    }
    setValue("");
    if (textareaRef.current) {
      textareaRef.current.style.height = "auto";
    }
    onSend(q);
  };

  const handleCancel = () => {
    onCancel();
    textareaRef.current?.focus();
  };

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    e.target.value = "";
    onFile(file);
  };

  return (
    <div className="shrink-0 px-4 sm:px-6 py-4 border-t border-[var(--color-border)]">
      <form onSubmit={handleSubmit} className="max-w-3xl mx-auto">
        <div className="rounded-3xl bg-white/80 backdrop-blur-xl border border-[var(--color-border)]
          shadow-sm
          focus-within:ring-4 focus-within:ring-brand/15 focus-within:border-brand/40
          transition-all duration-200 overflow-hidden">
          {/* 上方：多行输入区 */}
          <div className="px-4 pt-3.5">
            <textarea
              ref={textareaRef}
              value={value}
              onChange={handleChange}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  handleSubmit(e);
                }
              }}
              placeholder={
                disabled
                  ? "请先创建或上传简历开始对话..."
                  : asking
                  ? "AI 思考中，可输入补充信息（发送给正在思考的 AI）..."
                  : "告诉 AI 助手你的需求..."
              }
              disabled={disabled}
              rows={1}
              className="w-full bg-transparent border-0 outline-none resize-none
                text-sm text-[var(--color-text)] placeholder:text-[var(--color-text-muted)]
                py-1.5 max-h-32"
              aria-label="输入问题"
            />
          </div>

          {/* 底部：工具栏（附件 + 快捷标签 + 发送） */}
          <div className="flex items-center gap-1.5 px-3 pb-3 pt-1">
            {/* 隐藏的文件 input */}
            <input
              ref={fileInputRef}
              type="file"
              accept=".pdf,.docx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
              onChange={handleFileChange}
              className="hidden"
            />
            {/* 附件按钮 */}
            <button
              type="button"
              onClick={() => fileInputRef.current?.click()}
              disabled={uploading || asking || disabled}
              className="shrink-0 w-8 h-8 rounded-full flex items-center justify-center
                text-[var(--color-text-muted)] hover:text-brand hover:bg-brand/10
                active:scale-90 motion-reduce:active:scale-100
                transition-all cursor-pointer disabled:opacity-40 disabled:cursor-not-allowed"
              aria-label="上传简历"
            >
              {uploading ? (
                <span className="inline-block w-3.5 h-3.5 rounded-full border-2 border-current border-t-transparent animate-spin" aria-hidden="true" />
              ) : (
                <Paperclip size={16} weight="regular" aria-hidden="true" />
              )}
            </button>

            {/* 快捷标签（点击直接发送问题） */}
            <div className="flex flex-wrap items-center gap-0.5 min-w-0">
              {QUICK_TAGS.map((tag) => {
                const Icon = tag.icon;
                return (
                  <button
                    key={tag.label}
                    type="button"
                    onClick={() => onQuickTag(tag.question)}
                    disabled={asking || disabled}
                    className="inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded-full text-xs
                      text-[var(--color-text-secondary)] hover:text-brand hover:bg-brand/10
                      active:scale-[0.97] motion-reduce:active:scale-100
                      transition-all cursor-pointer
                      disabled:opacity-40 disabled:cursor-not-allowed
                      whitespace-nowrap"
                    aria-label={tag.label}
                  >
                    <Icon size={13} weight="regular" aria-hidden="true" />
                    {tag.label}
                  </button>
                );
              })}
            </div>

            <div className="flex-1" />

            {/* 发送/补充/取消按钮（圆形） */}
            {asking ? (
              <>
                {onInject && (
                  <button
                    type="submit"
                    disabled={!value.trim()}
                    className="shrink-0 w-9 h-9 rounded-full flex items-center justify-center
                      text-white bg-brand
                      hover:brightness-110 hover:shadow-lg hover:shadow-brand/25
                      active:scale-90 motion-reduce:active:scale-100
                      disabled:opacity-40 disabled:cursor-not-allowed
                      transition-all cursor-pointer"
                    aria-label="补充信息（发送给正在思考的 AI）"
                    title="补充信息"
                  >
                    <PaperPlaneRight size={16} weight="fill" aria-hidden="true" />
                  </button>
                )}
                <button
                  type="button"
                  onClick={handleCancel}
                  className="shrink-0 w-9 h-9 rounded-full flex items-center justify-center
                    text-white bg-red-500/80 hover:bg-red-500
                    active:scale-90 motion-reduce:active:scale-100
                    transition-all cursor-pointer"
                  aria-label="取消"
                >
                  <Stop size={16} weight="fill" aria-hidden="true" />
                </button>
              </>
            ) : (
              <button
                type="submit"
                disabled={!value.trim()}
                className="shrink-0 w-9 h-9 rounded-full flex items-center justify-center
                  text-white bg-brand
                  hover:brightness-110 hover:shadow-lg hover:shadow-brand/25
                  active:scale-90 motion-reduce:active:scale-100
                  disabled:opacity-40 disabled:cursor-not-allowed
                  transition-all cursor-pointer"
                aria-label="发送"
              >
                <PaperPlaneRight size={16} weight="fill" aria-hidden="true" />
              </button>
            )}
          </div>
        </div>
      </form>
    </div>
  );
}
