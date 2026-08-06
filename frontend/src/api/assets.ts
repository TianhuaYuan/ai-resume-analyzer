import { api } from "./client";

// ── 类型定义 ──

/** 知识资产类型：jd=岗位描述 / interview=面试记录 / note=笔记 */
export type KnowledgeAssetType = "jd" | "interview" | "note";

/**
 * 后端 /api/v1/assets 契约（已冻结）：
 * {id, asset_type, title, content, is_draft, version, index_version,
 *  indexed_hash, created_at, updated_at, indexed}
 * indexed = 向量索引是否最新就绪（懒索引脏标记派生字段）
 */
export interface KnowledgeAsset {
  id: number;
  asset_type: KnowledgeAssetType;
  title: string;
  content: string;
  is_draft: boolean;
  version: number;
  index_version: number | null;
  indexed_hash: string | null;
  created_at: string;
  updated_at: string;
  indexed: boolean;
}

export interface AssetListResponse {
  items: KnowledgeAsset[];
  total: number;
  page: number;
  limit: number;
}

export interface AssetListParams {
  asset_type?: KnowledgeAssetType;
  page?: number;
  limit?: number;
}

export interface AssetCreateInput {
  asset_type: KnowledgeAssetType;
  title: string;
  content: string;
  is_draft?: boolean;
}

export interface AssetUpdateInput {
  title?: string;
  content?: string;
  is_draft?: boolean;
}

// ── API 函数 ──

/** GET /api/v1/assets — 分页列表，可按 asset_type 筛选 */
export async function listAssets(params: AssetListParams = {}): Promise<AssetListResponse> {
  const qs = new URLSearchParams();
  if (params.asset_type) qs.set("asset_type", params.asset_type);
  qs.set("page", String(params.page ?? 1));
  qs.set("limit", String(params.limit ?? 20));
  return api.get(`/api/v1/assets?${qs}`) as Promise<AssetListResponse>;
}

/** POST /api/v1/assets — 新建（返回 201 AssetResponse） */
export async function createAsset(body: AssetCreateInput): Promise<KnowledgeAsset> {
  return api.post("/api/v1/assets", body) as Promise<KnowledgeAsset>;
}

/** PUT /api/v1/assets/{id} — 更新（title/content/is_draft 均可选） */
export async function updateAsset(id: number, body: AssetUpdateInput): Promise<KnowledgeAsset> {
  return api.put(`/api/v1/assets/${id}`, body) as Promise<KnowledgeAsset>;
}

/** DELETE /api/v1/assets/{id} — 删除（204，client 返回 null） */
export async function deleteAsset(id: number): Promise<null> {
  return api.delete(`/api/v1/assets/${id}`) as Promise<null>;
}
