import {
  createContext,
  useContext,
  useState,
  useCallback,
  useMemo,
  type ReactNode,
} from "react";

/**
 * PageHeaderProvider — 页面头部槽位（借鉴 Hermes PageHeaderProvider）。
 *
 * 允许页面通过 Context 声明自己的页头（标题覆盖 / 标题后扩展 / 右侧操作区），
 * 而不必每个页面各自维护页头布局——Provider 统一渲染 header，页面只注入内容。
 *
 * 槽位（页面内通过 usePageHeader 获取）：
 * - setTitle(str|null)：覆盖默认标题；null 恢复默认
 * - setAfterTitle(node)：标题右侧扩展区（副标题/标签）
 * - setEnd(node)：页头最右侧操作区（按钮组）
 *
 * 用法（页面内）：
 *   const { setTitle, setEnd } = usePageHeader();
 *   useEffect(() => {
 *     setTitle("我的简历");
 *     setEnd(<button>操作</button>);
 *     return () => { setTitle(null); setEnd(null); };
 *   }, [setTitle, setEnd]);
 */

interface PageHeaderContextValue {
  /** 覆盖默认标题；null 恢复默认 */
  setTitle: (title: string | null) => void;
  /** 标题后扩展区（副标题/标签） */
  setAfterTitle: (node: ReactNode) => void;
  /** 页头右侧操作区 */
  setEnd: (node: ReactNode) => void;
}

const PageHeaderContext = createContext<PageHeaderContextValue | null>(null);

export function usePageHeader(): PageHeaderContextValue {
  const ctx = useContext(PageHeaderContext);
  if (!ctx) throw new Error("usePageHeader must be used within PageHeaderProvider");
  return ctx;
}

interface PageHeaderProviderProps {
  /** 默认标题（页面未覆盖时显示） */
  title: string;
  /** 默认副标题（页面未设置 afterTitle 时显示） */
  subtitle?: string;
  /** 页面主体 */
  children: ReactNode;
}

export default function PageHeaderProvider({
  title,
  subtitle,
  children,
}: PageHeaderProviderProps) {
  const [overrideTitle, setOverrideTitle] = useState<string | null>(null);
  const [afterTitle, setAfterTitleNode] = useState<ReactNode>(null);
  const [end, setEndNode] = useState<ReactNode>(null);

  const setTitle = useCallback((t: string | null) => setOverrideTitle(t), []);
  const setAfterTitle = useCallback((n: ReactNode) => setAfterTitleNode(n), []);
  const setEnd = useCallback((n: ReactNode) => setEndNode(n), []);

  const value = useMemo(
    () => ({ setTitle, setAfterTitle, setEnd }),
    [setTitle, setAfterTitle, setEnd],
  );

  return (
    <PageHeaderContext.Provider value={value}>
      <div className="flex flex-col flex-1 overflow-hidden">
        <header className="shrink-0 flex items-center justify-between gap-3 px-6 py-3 border-b border-[var(--color-border)] bg-[var(--color-bg)]/80 backdrop-blur-sm">
          <div className="flex items-baseline gap-3 min-w-0">
            <h1 className="text-lg font-semibold text-[var(--color-text)] truncate">
              {overrideTitle ?? title}
            </h1>
            {afterTitle}
            {!afterTitle && subtitle && (
              <span className="text-xs text-[var(--color-text-muted)] truncate hidden sm:inline">
                {subtitle}
              </span>
            )}
          </div>
          <div className="shrink-0 flex items-center gap-2">{end}</div>
        </header>
        {children}
      </div>
    </PageHeaderContext.Provider>
  );
}
