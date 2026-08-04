/**
 * useInlineAI — 条目/字段级 AI 调用原语（optimize / check / rewrite）。
 *
 * 封装 builder API 三个内联端点 + request-id 竞态：
 * - 新请求发起时旧请求回调自动失效（reqIdRef 递增比对），避免结果落到已关闭/新菜单。
 * - 返回 loading / error / 三个 action，由调用方（FieldAIMenu 等）决定结果展示与回填。
 *
 * 自 InlineAIPanel 的竞态逻辑抽出，供条目级 AI 复用。
 */

import { useCallback, useRef, useState } from "react";
import { aiOptimize, aiCheck, aiRewrite } from "../../api/builder";
import type { AICheckIssue } from "../../api/builder";

export function useInlineAI(resumeId: number, moduleType: string) {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const reqIdRef = useRef(0);

  /** 统一执行器：竞态防护 + loading/error 状态。过期请求静默丢弃（返回 undefined）。 */
  const run = useCallback(async <T,>(fn: () => Promise<T>): Promise<T | undefined> => {
    const myReqId = ++reqIdRef.current;
    setLoading(true);
    setError("");
    try {
      const res = await fn();
      if (reqIdRef.current !== myReqId) return undefined;
      return res;
    } catch (err) {
      if (reqIdRef.current === myReqId) {
        setError(err instanceof Error ? err.message : "请求失败");
      }
      return undefined;
    } finally {
      if (reqIdRef.current === myReqId) setLoading(false);
    }
  }, []);

  /** 一键优化：返回 { optimized_text } */
  const optimize = useCallback(
    (text: string) =>
      run(() => aiOptimize(resumeId, text, moduleType)) as Promise<
        { optimized_text: string } | undefined
      >,
    [run, resumeId, moduleType],
  );

  /** 智能检查：返回 { issues } */
  const check = useCallback(
    (text: string) =>
      run(() => aiCheck(resumeId, text, moduleType)) as Promise<
        { issues: AICheckIssue[] } | undefined
      >,
    [run, resumeId, moduleType],
  );

  /** 智能改写：返回 { rewritten_text } */
  const rewrite = useCallback(
    (text: string, instruction: string) =>
      run(() => aiRewrite(resumeId, text, instruction, moduleType)) as Promise<
        { rewritten_text: string } | undefined
      >,
    [run, resumeId, moduleType],
  );

  return { loading, error, optimize, check, rewrite };
}
