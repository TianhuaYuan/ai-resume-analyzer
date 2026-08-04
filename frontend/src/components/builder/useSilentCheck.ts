/**
 * useSilentCheck — 静默纠错原语（不打断输入，角标提示）。
 *
 * 编辑停顿后自动检查内容质量，仅通过状态暴露结果，不弹任何面板：
 * - 防抖：停止输入 2.5s 才触发，避免打字中连续请求。
 * - 限流：两次实际请求间隔 ≥ 20s，防 LLM 调用风暴（超频直接跳过，保留上次结果）。
 * - 竞态：request-id 递增，旧请求结果自动丢弃。
 * - 空文本跳过（< 20 字符视为未填写/无检查价值）。
 *
 * 返回 { state, issues, error, schedule, cancel, clear }：
 * - schedule(text)：编辑停顿后调用，内部防抖到点后检查。
 * - cancel()：卸载/切换时清理挂起定时器。
 * - clear()：重置结果（如模块内容被清空）。
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { aiCheck } from "../../api/builder";
import type { AICheckIssue } from "../../api/builder";

/** 防抖间隔（ms） */
const DEBOUNCE_MS = 2500;
/** 限流间隔（ms） */
const THROTTLE_MS = 20000;
/** 内容最小长度（低于则跳过，避免空模块无谓调用） */
const MIN_TEXT_LENGTH = 20;

export type SilentCheckState = "idle" | "checking" | "done";

/**
 * @param checkField 可选：聚焦检查某字段（如 "description"），透传给后端 /ai/check。
 *                   缺省 = 模块级检查，LLM 仍会在 issue.field 标注所属字段。
 */
export function useSilentCheck(resumeId: number, moduleType: string, checkField?: string) {
  const [state, setState] = useState<SilentCheckState>("idle");
  const [issues, setIssues] = useState<AICheckIssue[]>([]);
  const [error, setError] = useState("");

  const reqIdRef = useRef(0);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const lastRunRef = useRef(0);

  const runCheck = useCallback(
    (text: string) => {
      const now = Date.now();
      // 限流：距上次发起 < 20s 直接跳过（保留上次结果，不更新 state）
      if (now - lastRunRef.current < THROTTLE_MS) return;
      lastRunRef.current = now;

      const myReqId = ++reqIdRef.current;
      setState("checking");
      setError("");

      aiCheck(resumeId, text, moduleType, checkField)
        .then((res) => {
          if (reqIdRef.current !== myReqId) return;
          setIssues(res.issues);
          setState("done");
        })
        .catch((err: unknown) => {
          if (reqIdRef.current !== myReqId) return;
          setError(err instanceof Error ? err.message : "检查失败");
          setState("done");
        });
    },
    [resumeId, moduleType, checkField],
  );

  /** 编辑停顿后触发（防抖） */
  const schedule = useCallback(
    (text: string) => {
      if (!text || text.trim().length < MIN_TEXT_LENGTH) return;
      if (debounceRef.current) clearTimeout(debounceRef.current);
      debounceRef.current = setTimeout(() => runCheck(text), DEBOUNCE_MS);
    },
    [runCheck],
  );

  /** 清理挂起定时器 */
  const cancel = useCallback(() => {
    if (debounceRef.current) {
      clearTimeout(debounceRef.current);
      debounceRef.current = null;
    }
  }, []);

  /** 重置全部结果（卸载 / 内容清空时） */
  const clear = useCallback(() => {
    cancel();
    reqIdRef.current++;
    setIssues([]);
    setError("");
    setState("idle");
  }, [cancel]);

  // 卸载清理
  useEffect(() => cancel, [cancel]);

  return { state, issues, error, schedule, cancel, clear };
}
