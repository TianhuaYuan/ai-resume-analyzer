/**
 * T37: 产品分析前端埋点。
 *
 * - captureCtaSource: 页面加载时捕获 URL 的 ?source= 参数存入 localStorage（cta_source）
 * - trackEvent: 上报事件到 POST /api/v1/track/events，best-effort（失败静默吞掉）
 *
 * 埋点失败绝不能影响核心流程（登录/上传/导出），故 trackEvent 内部 catch 所有错误。
 */

import { api } from "./client";

const CTA_SOURCE_KEY = "cta_source";

/** 读取已捕获的 CTA 来源渠道（可能为 null） */
export function getCtaSource(): string | null {
  return localStorage.getItem(CTA_SOURCE_KEY);
}

/** 捕获 URL 中的 ?source= 参数并持久化，随后从地址栏清理该参数（防刷新重复写入） */
export function captureCtaSource(): void {
  try {
    const url = new URL(window.location.href);
    const source = url.searchParams.get("source");
    if (source && source.trim()) {
      localStorage.setItem(CTA_SOURCE_KEY, source.trim().slice(0, 50));
      // 清理 URL 中的 source 参数，避免刷新页面时重复捕获
      url.searchParams.delete("source");
      window.history.replaceState(null, "", url.toString());
    }
  } catch {
    // URL 解析失败等极端情况静默忽略
  }
}

/**
 * 记录一条产品事件（best-effort）。
 *
 * @param eventName 事件名，如 user.login / resume.upload
 * @param source    可选 CTA 来源渠道
 * @param metadata  可选附加上下文
 */
export async function trackEvent(
  eventName: string,
  source?: string | null,
  metadata?: Record<string, unknown>,
): Promise<void> {
  try {
    // 路径用 /track 而非 /analytics：避开浏览器广告拦截扩展的 analytics 关键词拦截
    await api.post("/api/v1/track/events", {
      event_name: eventName,
      source: source || undefined,
      metadata,
    });
  } catch {
    // 静默失败：埋点不影响核心流程
  }
}
