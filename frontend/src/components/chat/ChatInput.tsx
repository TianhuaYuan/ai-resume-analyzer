import { useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import { FileText, Languages, Briefcase, Mic, Map, Paperclip, ArrowUp, Square } from "lucide-react";

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
  { icon: Languages, label: "简历翻译", question: "请将这份简历翻译为英文" },
  { icon: Briefcase, label: "校招推荐", question: "请实时搜索最近的校招和社招岗位机会" },
  { icon: Mic, label: "面试指导", question: "请根据这份简历模拟一场面试" },
  { icon: Map, label: "职业规划", question: "请帮我分析我的职业发展方向" },
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
  // P4-3 斜杠命令自动补全（借鉴 Hermes SlashPopover）：输入以 / 开头时弹出命令列表
  const [slashActive, setSlashActive] = useState(false);
  const [slashIndex, setSlashIndex] = useState(0);

  // 斜杠命令候选：基于快捷标签派生（label → 命令别名，question → 填充文本）
  const slashCommands = useMemo(() => {
    const aliases: Record<string, string> = {
      简历诊断: "diagnose",
      简历翻译: "translate",
      校招推荐: "jobs",
      面试指导: "interview",
      职业规划: "career",
    };
    return QUICK_TAGS.map((tag) => ({
      alias: aliases[tag.label] ?? tag.label.toLowerCase(),
      label: tag.label,
      question: tag.question,
    }));
  }, []);

  // 当前匹配的 slash 命令（输入 "/xxx" 时过滤）
  const slashMatches = useMemo(() => {
    if (!slashActive) return [];
    const query = value.slice(1).trim().toLowerCase();
    if (!query) return slashCommands;
    return slashCommands.filter(
      (c) =>
        c.alias.includes(query) ||
        c.label.toLowerCase().includes(query) ||
        c.question.toLowerCase().includes(query),
    );
  }, [slashActive, value, slashCommands]);

  // 输入变化时：检测是否触发斜杠命令模式（输入框开头是 / 且非连续）
  useEffect(() => {
    const isSlash = value.startsWith("/") && !value.startsWith("//") && value.length > 0;
    setSlashActive(isSlash);
    setSlashIndex(0);
  }, [value]);

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

  /** P4-3: 应用选中的斜杠命令（填充问题文本 + 关闭弹出层） */
  const applySlashCommand = (question: string) => {
    setValue(question);
    setSlashActive(false);
    setSlashIndex(0);
    if (textareaRef.current) {
      textareaRef.current.focus();
      textareaRef.current.style.height = "auto";
      textareaRef.current.style.height =
        Math.min(textareaRef.current.scrollHeight, 128) + "px";
    }
  };

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    e.target.value = "";
    onFile(file);
  };

  return (
    <div className="shrink-0 px-4 sm:px-6 py-4 border-t border-[var(--color-border)]">
      <form onSubmit={handleSubmit} className="max-w-[58rem] mx-auto">
        <div className="rounded-3xl bg-white/80 backdrop-blur-xl border border-[var(--color-border)]
          shadow-sm
          focus-within:ring-4 focus-within:ring-brand/15 focus-within:border-brand/40
          transition-all duration-200 overflow-visible">
          {/* 上方：多行输入区 */}
          <div className="relative px-4 pt-3.5">
            <textarea
              ref={textareaRef}
              value={value}
              onChange={handleChange}
              onKeyDown={(e) => {
                // P4-3: 斜杠命令弹出层键盘导航
                if (slashActive && slashMatches.length > 0) {
                  if (e.key === "ArrowDown") {
                    e.preventDefault();
                    setSlashIndex((i) => (i + 1) % slashMatches.length);
                    return;
                  }
                  if (e.key === "ArrowUp") {
                    e.preventDefault();
                    setSlashIndex(
                      (i) => (i - 1 + slashMatches.length) % slashMatches.length,
                    );
                    return;
                  }
                  if (e.key === "Tab" || e.key === "Enter") {
                    e.preventDefault();
                    const cmd = slashMatches[Math.min(slashIndex, slashMatches.length - 1)];
                    if (cmd) {
                      applySlashCommand(cmd.question);
                      return;
                    }
                  }
                  if (e.key === "Escape") {
                    e.preventDefault();
                    setSlashActive(false);
                    return;
                  }
                }
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
                  : "告诉 AI 助手你的需求...（输入 / 唤起快捷命令）"
              }
              disabled={disabled}
              rows={1}
              className="w-full bg-transparent border-0 outline-none resize-none
                text-sm text-[var(--color-text)] placeholder:text-[var(--color-text-muted)]
                py-1.5 max-h-32"
              aria-label="输入问题"
            />

            {/* P4-3: 斜杠命令弹出层（输入 / 前缀时出现） */}
            {slashActive && slashMatches.length > 0 && (
              <div className="absolute z-50 left-4 right-4 bottom-full mb-2 max-h-56 overflow-y-auto rounded-list
                bg-[var(--color-surface)] border border-[var(--color-border)] shadow-xl
                animate-fade-in-up motion-reduce:animate-none">
                <div className="px-3 py-1.5 text-[10px] uppercase tracking-wider
                  text-[var(--color-text-muted)] border-b border-[var(--color-border)]">
                  快捷命令
                </div>
                {slashMatches.map((cmd, i) => (
                  <button
                    key={cmd.alias}
                    type="button"
                    onMouseEnter={() => setSlashIndex(i)}
                    onClick={() => applySlashCommand(cmd.question)}
                    className={`w-full flex items-center gap-2 px-3 py-2 text-left text-xs transition-colors cursor-pointer
                      ${i === slashIndex
                        ? "bg-brand/10 text-brand"
                        : "text-[var(--color-text-secondary)] hover:bg-[var(--color-bg-secondary)]"}`}
                  >
                    <span className="font-mono text-[var(--color-text-muted)] shrink-0">
                      /{cmd.alias}
                    </span>
                    <span className="truncate">{cmd.label}</span>
                  </button>
                ))}
              </div>
            )}
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
                <Paperclip size={16} aria-hidden="true" />
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
                    <Icon size={13} aria-hidden="true" />
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
                    <ArrowUp size={16} strokeWidth={2.25} aria-hidden="true" />
                  </button>
                )}
                <button
                  type="button"
                  onClick={handleCancel}
                  className="shrink-0 w-9 h-9 rounded-full flex items-center justify-center
                    text-white bg-danger/80 hover:bg-danger
                    active:scale-90 motion-reduce:active:scale-100
                    transition-all cursor-pointer"
                  aria-label="取消"
                >
                  <Square size={16} fill="currentColor" aria-hidden="true" />
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
                <ArrowUp size={16} strokeWidth={2.25} aria-hidden="true" />
              </button>
            )}
          </div>
        </div>
      </form>
    </div>
  );
}
