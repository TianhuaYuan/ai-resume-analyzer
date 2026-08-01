/**
 * Task 11: useHistory — 通用撤销/重做历史管理 hook。
 *
 * 功能：
 * - 维护状态历史栈（最大 50 条）
 * - setState 时防抖 500ms 记录历史（避免每次按键都记录）
 * - undo() / redo() 在历史栈中导航
 * - 支持重置历史（加载新简历时）
 *
 * 设计要点：
 * - 使用 ref 跟踪 history/pointer 避免闭包陈旧值
 * - forceUpdate 触发 canUndo/canRedo 重算
 * - undo 前自动 flush 待提交的历史
 */

import { useCallback, useEffect, useRef, useState } from "react";

interface UseHistoryOptions {
  /** 历史栈最大长度，默认 50 */
  maxHistory?: number;
  /** 记录延迟（ms），默认 500 */
  debounceMs?: number;
}

export function useHistory<T>(
  initialState: T,
  options: UseHistoryOptions = {},
) {
  const { maxHistory = 50, debounceMs = 500 } = options;

  const [state, setStateInternal] = useState(initialState);
  const [, forceUpdate] = useState(0);

  const historyRef = useRef<T[]>([initialState]);
  const pointerRef = useRef(0);
  const stateRef = useRef(initialState);
  const commitTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const rerender = useCallback(() => forceUpdate((v) => v + 1), []);

  /** 将当前 state 推入历史栈（立即执行，清除待提交计时器） */
  const commit = useCallback(() => {
    if (commitTimerRef.current) {
      clearTimeout(commitTimerRef.current);
      commitTimerRef.current = null;
    }
    const truncated = historyRef.current.slice(0, pointerRef.current + 1);
    truncated.push(stateRef.current);
    if (truncated.length > maxHistory) {
      truncated.shift();
    }
    pointerRef.current = truncated.length - 1;
    historyRef.current = truncated;
    rerender();
  }, [maxHistory, rerender]);

  /**
   * 更新状态并防抖记录历史。
   * 适合频繁更新场景（如文本输入）：500ms 内连续调用只记录最后一次。
   */
  const setState = useCallback(
    (next: T | ((prev: T) => T)) => {
      const value =
        typeof next === "function"
          ? (next as (prev: T) => T)(stateRef.current)
          : next;
      stateRef.current = value;
      setStateInternal(value);

      if (commitTimerRef.current) {
        clearTimeout(commitTimerRef.current);
      }
      commitTimerRef.current = setTimeout(() => {
        commit();
      }, debounceMs);
    },
    [commit, debounceMs],
  );

  /** 撤销到上一历史状态 */
  const undo = useCallback(() => {
    // 先提交待记录的历史
    if (commitTimerRef.current) {
      commit();
    }
    if (pointerRef.current > 0) {
      pointerRef.current--;
      const prev = historyRef.current[pointerRef.current];
      stateRef.current = prev;
      setStateInternal(prev);
      rerender();
    }
  }, [commit, rerender]);

  /** 重做到下一历史状态 */
  const redo = useCallback(() => {
    if (pointerRef.current < historyRef.current.length - 1) {
      pointerRef.current++;
      const next = historyRef.current[pointerRef.current];
      stateRef.current = next;
      setStateInternal(next);
      rerender();
    }
  }, [rerender]);

  /** 重置历史栈（加载新数据时调用） */
  const reset = useCallback(
    (newState: T) => {
      if (commitTimerRef.current) {
        clearTimeout(commitTimerRef.current);
        commitTimerRef.current = null;
      }
      stateRef.current = newState;
      pointerRef.current = 0;
      historyRef.current = [newState];
      setStateInternal(newState);
      rerender();
    },
    [rerender],
  );

  // 卸载时清理计时器
  useEffect(() => {
    return () => {
      if (commitTimerRef.current) {
        clearTimeout(commitTimerRef.current);
      }
    };
  }, []);

  return {
    state,
    setState,
    undo,
    redo,
    canUndo: pointerRef.current > 0,
    canRedo: pointerRef.current < historyRef.current.length - 1,
    reset,
  };
}
