/**
 * 简历分析进度全局缓存。
 *
 * WebSocket 收到 analysis_progress 时写入，
 * 弹窗打开时直接读取，零网络延迟。
 * 分析完成后（completed=true）保留最后状态。
 */

interface CachedProgress {
  completed: number;
  total: number;
  current_type: string;
  current_type_label: string;
}

const store = new Map<number, CachedProgress>();

export function setCachedProgress(resumeId: number, progress: CachedProgress) {
  store.set(resumeId, progress);
}

export function getCachedProgress(resumeId: number): CachedProgress | undefined {
  return store.get(resumeId);
}

export function clearCachedProgress(resumeId: number) {
  store.delete(resumeId);
}
