import { api } from "./client";

// ── 类型定义 ──

export interface UserFeedbackItem {
  id: number;
  user_id: number;
  content: string;
  type: string;
  status: string;
  created_at: string;
}

export interface PublicFeedbackItem {
  id: number;
  content: string;
  type: string;
  status: string;
  created_at: string;
  user_display: string;
  likes_count: number;
  is_liked: boolean;
}

export interface PublicFeedbackListResponse {
  items: PublicFeedbackItem[];
  total: number;
}

// ── 反馈类型 ──

export const FEEDBACK_TYPES = [
  { value: "bug", label: "Bug 反馈" },
  { value: "feature", label: "功能建议" },
  { value: "ux", label: "体验优化" },
  { value: "other", label: "其他" },
] as const;

// ── API 函数 ──

/** 提交反馈 */
export async function submitFeedback(
  content: string,
  type: string
): Promise<{ id: number; detail: string }> {
  return api.post("/api/v1/feedback", { content, type }) as Promise<{
    id: number;
    detail: string;
  }>;
}

/** 公开反馈列表（所有登录用户可看） */
export async function listPublicFeedback(
  limit = 50,
  offset = 0
): Promise<PublicFeedbackListResponse> {
  return api.get(
    `/api/v1/feedback/public?limit=${limit}&offset=${offset}`
  ) as Promise<PublicFeedbackListResponse>;
}

/** 点赞/取消点赞反馈（toggle） */
export async function toggleFeedbackLike(
  feedbackId: number
): Promise<{ likes_count: number; is_liked: boolean }> {
  return api.post(
    `/api/v1/feedback/public/${feedbackId}/like`
  ) as Promise<{ likes_count: number; is_liked: boolean }>;
}

/** 管理员查看反馈列表 */
export async function listFeedback(
  limit = 20,
  offset = 0
): Promise<{ items: UserFeedbackItem[]; total: number }> {
  return api.get(
    `/api/v1/feedback?limit=${limit}&offset=${offset}`
  ) as Promise<{ items: UserFeedbackItem[]; total: number }>;
}
