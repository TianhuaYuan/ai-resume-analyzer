import { useEffect, useState, useRef, type ChangeEvent } from "react";
import { useNavigate } from "react-router-dom";
import {
  listResumes,
  uploadResume,
  generateIdempotencyKey,
} from "../api/resumes";
import { createBuilderResume } from "../api/builder";
import ResumeEmptyState from "../components/ResumeEmptyState";
import { useToast } from "../components/Toast";
import { trackEvent, getCtaSource } from "../api/analytics";

// 允许 PDF + DOCX，单文件上限 10MB（与旧列表页校验一致）
const MAX_FILE_SIZE = 10 * 1024 * 1024;
const ACCEPTED_TYPES = [
  "application/pdf",
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
];
const ACCEPTED_EXTS = [".pdf", ".docx"];

function validateFile(file: File): string | null {
  const lowerName = file.name.toLowerCase();
  const extOk = ACCEPTED_EXTS.some((ext) => lowerName.endsWith(ext));
  const typeOk = ACCEPTED_TYPES.includes(file.type);
  if (!extOk && !typeOk) return "仅支持 PDF / DOCX 文件";
  if (file.size > MAX_FILE_SIZE) return "文件大小不能超过 10MB";
  return null;
}

/**
 * 首页 — 智能分流入口：
 * - 有简历 → replace 重定向到最近一份简历的问答页 /resumes/:id
 *   （后端 listResumes 按 created_at desc 排序，items[0] 即最近创建）
 * - 无简历 → 渲染引导页（新建简历 / 上传简历两个入口）
 */
export default function HomePage() {
  const navigate = useNavigate();
  const toast = useToast();

  const [status, setStatus] = useState<"loading" | "empty">("loading");
  const [uploading, setUploading] = useState(false);
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState("");
  const fileInputRef = useRef<HTMLInputElement>(null);

  // 挂载时查一次简历列表，决定重定向 or 引导页
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const data = await listResumes(1);
        if (cancelled) return;
        if (data.items.length > 0) {
          // replace：防止历史栈堆积，浏览器返回不会回到空首页
          navigate(`/resumes/${data.items[0].id}`, { replace: true });
        } else {
          setStatus("empty");
        }
      } catch {
        // 列表查询失败 → 保守降级渲染引导页（上传/新建不依赖列表，仍可用）
        if (!cancelled) setStatus("empty");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [navigate]);

  const handleUpload = async (e: ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    // 清空 input 值允许重复上传同一文件
    e.target.value = "";

    const invalidReason = validateFile(file);
    if (invalidReason) {
      setError(invalidReason);
      return;
    }

    setError("");
    setUploading(true);
    try {
      const key = await generateIdempotencyKey(file);
      const result = await uploadResume(file, key);
      // T37: 上传成功埋点（best-effort）
      void trackEvent("resume.upload", getCtaSource());
      // 不轮询，直接跳转新简历问答页（Sidebar/WebSocket 负责状态刷新）
      navigate(`/resumes/${result.id}`);
    } catch {
      setError("上传失败，请重试");
    } finally {
      setUploading(false);
    }
  };

  const handleCreate = async () => {
    setCreating(true);
    setError("");
    try {
      const resume = await createBuilderResume({ filename: "未命名简历" });
      toast.success("已创建新简历，开始编辑吧");
      // ?tab=edit → AppLayout 初始化为编辑 tab，直达编辑页
      navigate(`/resumes/${resume.id}?tab=edit`);
    } catch (err: unknown) {
      toast.error(err instanceof Error ? err.message : "创建简历失败");
    } finally {
      setCreating(false);
    }
  };

  return (
    <div className="min-h-screen bg-[var(--color-bg)]">
      <div className="max-w-4xl mx-auto px-6 md:px-8 lg:px-12">
        {/* 隐藏文件输入（始终在 DOM 中） */}
        <input
          ref={fileInputRef}
          type="file"
          accept=".pdf,.docx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
          className="hidden"
          onChange={handleUpload}
        />

        {/* 错误提示 */}
        {error && (
          <div className="mt-6 p-3.5 border-b-2 border-[var(--color-text)] text-[var(--color-text)] text-sm animate-shake flex items-center justify-between gap-3">
            <span className="font-mono-label tracking-widest uppercase text-xs">{error}</span>
            <button
              onClick={() => setError("")}
              className="text-[var(--color-text-muted)] hover:text-[var(--color-text)] cursor-pointer"
              aria-label="关闭"
            >
              ✕
            </button>
          </div>
        )}

        {status === "loading" ? (
          <div className="flex items-center justify-center py-32">
            <span className="inline-block w-5 h-5 rounded-full border-2 border-indigo-400 border-t-transparent animate-spin mr-2" />
            <span className="text-sm text-[var(--color-text-secondary)]">加载中...</span>
          </div>
        ) : (
          <ResumeEmptyState
            onCreate={handleCreate}
            onUpload={() => fileInputRef.current?.click()}
            uploading={uploading || creating}
          />
        )}
      </div>
    </div>
  );
}
