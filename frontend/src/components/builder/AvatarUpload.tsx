/**
 * AvatarUpload — UP 简历对齐的头像上传组件。
 *
 * 功能：
 * - 有头像：圆形展示 80x80px，hover 显示半透明遮罩（编辑 / 删除按钮）
 * - 无头像：虚线圆圈占位符 + 上传图标 + "上传头像"文字
 * - 点击编辑 / 占位符 → 触发隐藏 file input → 选文件后立即上传
 * - 上传中：spinner + "上传中..." 文字，禁用交互
 * - 上传成功 → onUpload(url)；点击删除 → onDelete()
 * - 文件校验：类型 image/jpeg|png|webp，大小 ≤ 5MB
 * - 错误处理：console.error + 行内提示
 */

import { memo, useRef, useState, useCallback } from "react";
import { User, Trash, Pencil, LoaderCircle } from "lucide-react";
import { uploadAvatar } from "../../api/builder";

// ── Props ──────────────────────────────────────────────────────

interface AvatarUploadProps {
  /** 简历 ID（上传接口用） */
  resumeId: number;
  /** 当前头像 URL，null 表示无头像 */
  avatarUrl: string | null;
  /** 上传成功回调，回传新的头像 URL */
  onUpload: (url: string) => void;
  /** 删除头像回调 */
  onDelete: () => void;
}

// ── 常量 ────────────────────────────────────────────────────────

/** 文件大小上限：5MB */
const MAX_FILE_SIZE = 5 * 1024 * 1024;

/** 允许的文件类型 */
const ACCEPTED_TYPES = ["image/jpeg", "image/png", "image/webp"] as const;

// ── 组件 ────────────────────────────────────────────────────────

function AvatarUploadInner({
  resumeId,
  avatarUrl,
  onUpload,
  onDelete,
}: AvatarUploadProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  /** 触发隐藏 file input 的点击 */
  const triggerFileInput = useCallback(() => {
    if (uploading) return;
    setError(null);
    inputRef.current?.click();
  }, [uploading]);

  /** 文件选择 → 校验 → 上传 */
  const handleFileChange = useCallback(
    async (e: React.ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0];
      // 重置 value，允许重复选择同一文件
      e.target.value = "";
      if (!file) return;

      // 类型校验
      if (!ACCEPTED_TYPES.includes(file.type as (typeof ACCEPTED_TYPES)[number])) {
        const msg = "仅支持 JPG / PNG / WebP 格式";
        setError(msg);
        console.error("[AvatarUpload] 不支持的文件类型:", file.type);
        return;
      }

      // 大小校验
      if (file.size > MAX_FILE_SIZE) {
        const msg = "文件大小不能超过 5MB";
        setError(msg);
        console.error(
          "[AvatarUpload] 文件过大:",
          `${(file.size / 1024 / 1024).toFixed(2)}MB`,
        );
        return;
      }

      setUploading(true);
      setError(null);
      try {
        const { avatar_url } = await uploadAvatar(resumeId, file);
        onUpload(avatar_url);
      } catch (err) {
        console.error("[AvatarUpload] 上传失败:", err);
        setError("上传失败，请重试");
      } finally {
        setUploading(false);
      }
    },
    [resumeId, onUpload],
  );

  /** 删除头像 */
  const handleDelete = useCallback(
    (e: React.MouseEvent) => {
      e.stopPropagation();
      if (uploading) return;
      setError(null);
      onDelete();
    },
    [uploading, onDelete],
  );

  /** 编辑按钮：阻止冒泡后触发 file input（容器本身也会触发，这里显式处理避免歧义） */
  const handleEditClick = useCallback(
    (e: React.MouseEvent) => {
      e.stopPropagation();
      triggerFileInput();
    },
    [triggerFileInput],
  );

  /** 键盘可达性：Enter / Space 触发上传 */
  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        triggerFileInput();
      }
    },
    [triggerFileInput],
  );

  const hasAvatar = Boolean(avatarUrl);

  return (
    <div className="flex flex-col items-center gap-2">
      <div
        className="relative w-20 h-20 rounded-full overflow-hidden shrink-0 group cursor-pointer outline-none focus-visible:ring-2 focus-visible:ring-brand/50"
        onClick={triggerFileInput}
        onKeyDown={handleKeyDown}
        role="button"
        tabIndex={uploading ? -1 : 0}
        aria-label={hasAvatar ? "更换头像" : "上传头像"}
        title={hasAvatar ? "更换头像" : "上传头像"}
      >
        {/* 隐藏的 file input */}
        <input
          ref={inputRef}
          type="file"
          accept={ACCEPTED_TYPES.join(",")}
          className="hidden"
          onChange={handleFileChange}
          disabled={uploading}
        />

        {uploading ? (
          // 上传中：spinner + 文字
          <div className="w-full h-full flex flex-col items-center justify-center bg-[var(--color-bg)] border border-[var(--color-border)]">
            <LoaderCircle
              size={20}
              fill="currentColor"
              className="text-[var(--color-text-secondary)] animate-spin"
              aria-hidden="true"
            />
            <span className="text-[10px] text-[var(--color-text-secondary)] mt-1">
              上传中...
            </span>
          </div>
        ) : hasAvatar ? (
          // 有头像：图片 + hover 遮罩
          <>
            <img
              src={avatarUrl as string}
              alt="头像"
              className="w-full h-full object-cover"
              draggable={false}
            />
            <div className="absolute inset-0 bg-black/50 opacity-0 group-hover:opacity-100 transition-opacity duration-150 flex items-center justify-center gap-2">
              <button
                type="button"
                className="p-1.5 rounded-full text-white hover:bg-white/25 transition-colors"
                onClick={handleEditClick}
                aria-label="编辑头像"
                title="编辑"
              >
                <Pencil size={16} fill="currentColor" />
              </button>
              <button
                type="button"
                className="p-1.5 rounded-full text-white hover:bg-white/25 transition-colors"
                onClick={handleDelete}
                aria-label="删除头像"
                title="删除"
              >
                <Trash size={16} fill="currentColor" />
              </button>
            </div>
          </>
        ) : (
          // 无头像：虚线占位符
          <div className="w-full h-full flex flex-col items-center justify-center border-2 border-dashed border-[var(--color-border)] bg-[var(--color-bg)] group-hover:border-brand/50 transition-colors">
            <User
              size={24}
              fill="currentColor"
              className="text-[var(--color-text-secondary)]"
              aria-hidden="true"
            />
            <span className="text-[10px] text-[var(--color-text-secondary)] mt-1">
              上传头像
            </span>
          </div>
        )}
      </div>

      {/* 错误提示 */}
      {error && (
        <p className="text-xs text-danger max-w-[120px] text-center leading-tight">
          {error}
        </p>
      )}
    </div>
  );
}

export const AvatarUpload = memo(AvatarUploadInner);
