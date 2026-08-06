/**
 * E2: 改写审阅队列（PendingChange）API 客户端。
 *
 * 改写类工具（rewrite_star/translate/rewrite_resume）落库后在后端生成
 * 字段级 diff 记录（before/after/rationale），前端逐条接受/丢弃。
 *
 * 端点（user_id 隔离）：
 * - GET    /api/v1/resumes/{resumeId}/pending-changes
 * - POST   /api/v1/resumes/{resumeId}/pending-changes/{id}/accept
 * - POST   /api/v1/resumes/{resumeId}/pending-changes/{id}/reject
 * - DELETE /api/v1/resumes/{resumeId}/pending-changes
 */

import { api } from "./client";

export type PendingChangeStatus = "pending" | "accepted" | "rejected";

export interface PendingChange {
  id: number;
  resume_id: number;
  tool_name: string;
  module_type: string;
  /** 点号路径：items.<item_id>.<field> / 平铺 field / items.<item_id> */
  field_path: string;
  before: unknown;
  after: unknown;
  rationale: string;
  status: PendingChangeStatus;
  created_at: string;
}

export interface PendingChangeListResponse {
  items: PendingChange[];
  total: number;
}

/** 列出简历的待审阅改动。 */
export async function listPendingChanges(
  resumeId: number,
): Promise<PendingChangeListResponse> {
  return api.get(
    `/api/v1/resumes/${resumeId}/pending-changes`,
  ) as Promise<PendingChangeListResponse>;
}

/** 接受（保留）一条改动。 */
export async function acceptPendingChange(
  resumeId: number,
  changeId: number,
): Promise<PendingChange> {
  return api.post(
    `/api/v1/resumes/${resumeId}/pending-changes/${changeId}/accept`,
  ) as Promise<PendingChange>;
}

/** 拒绝（还原字段为 before）一条改动。 */
export async function rejectPendingChange(
  resumeId: number,
  changeId: number,
): Promise<PendingChange> {
  return api.post(
    `/api/v1/resumes/${resumeId}/pending-changes/${changeId}/reject`,
  ) as Promise<PendingChange>;
}

/** 清空简历的全部待审阅改动。 */
export async function clearPendingChanges(
  resumeId: number,
): Promise<{ cleared: number }> {
  return api.delete(
    `/api/v1/resumes/${resumeId}/pending-changes`,
  ) as Promise<{ cleared: number }>;
}
