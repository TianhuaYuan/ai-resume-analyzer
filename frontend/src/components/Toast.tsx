import {
  createContext,
  useContext,
  useState,
  useCallback,
  useEffect,
  useRef,
  useMemo,
  type ReactNode,
} from "react";
import { X } from "@phosphor-icons/react";

// ── Types ──

type ToastType = "success" | "error" | "info";

interface ToastItem {
  id: number;
  type: ToastType;
  message: string;
  title?: string;
}

interface ToastContextValue {
  success: (message: string, options?: { title?: string }) => void;
  error: (message: string, options?: { title?: string }) => void;
  info: (message: string, options?: { title?: string }) => void;
  toasts: ToastItem[];
  remove: (id: number) => void;
}

const ToastContext = createContext<ToastContextValue | null>(null);

// ── Auto-dismiss timing（null 表示不自动消失，需手动关闭）──
// error 自动关闭（10s）：WS 推送的失败提示（如简历分析失败）之前永不消失
// 一直挂在界面（用户反馈「缺失的 websocket 提示不会自动关闭」）；
// 10s 足够阅读且仍保留 X 手动关闭
const AUTO_DISMISS_MS: Record<ToastType, number | null> = {
  success: 3000,
  error: 10000,
  info: 4000,
};

const MAX_TOASTS = 3;

// ── ARIA 属性（按类型区分，符合 WAI-ARIA Toast 模式）──
// success/info: role=status（隐含 polite）+ 显式 aria-live=polite
// error: role=alert（隐含 assertive）+ 显式 aria-live=assertive
const ARIA_ATTRS: Record<
  ToastType,
  { role: "status" | "alert"; ariaLive: "polite" | "assertive" }
> = {
  success: { role: "status", ariaLive: "polite" },
  error: { role: "alert", ariaLive: "assertive" },
  info: { role: "status", ariaLive: "polite" },
};

// ── Provider ──

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<ToastItem[]>([]);
  const idRef = useRef(0);

  const add = useCallback((type: ToastType, message: string, options?: { title?: string }) => {
    const id = ++idRef.current;
    setToasts((prev) => {
      const next = [...prev, { id, type, message, title: options?.title }];
      if (next.length > MAX_TOASTS) next.shift();
      return next;
    });
  }, []);

  const remove = useCallback((id: number) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  const success = useCallback((message: string, options?: { title?: string }) => add("success", message, options), [add]);
  const error = useCallback((message: string, options?: { title?: string }) => add("error", message, options), [add]);
  const info = useCallback((message: string, options?: { title?: string }) => add("info", message, options), [add]);

  // memoize context value：success/error/info/remove 均稳定，仅 toasts 变化时重建，
  // 避免 ToastProvider 每次渲染都新建对象 → 所有 useToast 消费者级联重渲染
  const value = useMemo(
    () => ({ success, error, info, toasts, remove }),
    [success, error, info, toasts, remove]
  );

  return (
    <ToastContext.Provider value={value}>
      {children}
    </ToastContext.Provider>
  );
}

// ── Hook ──

export function useToast() {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error("useToast must be used within ToastProvider");
  return ctx;
}

// ── Container ──

const BG_CLASS: Record<ToastType, string> = {
  success: "bg-success",
  error: "bg-danger",
  info: "bg-info",
};

function ToastEntry({ item, onDismiss }: { item: ToastItem; onDismiss: (id: number) => void }) {
  const { role, ariaLive } = ARIA_ATTRS[item.type];
  const duration = AUTO_DISMISS_MS[item.type];

  useEffect(() => {
    // duration=null（error）时不注册自动消失 timer
    if (duration === null) return;
    const timer = setTimeout(() => onDismiss(item.id), duration);
    return () => clearTimeout(timer);
  }, [item, onDismiss, duration]);

  return (
    <div
      role={role}
      aria-live={ariaLive}
      className={`${BG_CLASS[item.type]} text-white px-4 py-3 rounded-lg shadow-lg
        flex items-center justify-between gap-3 min-w-[280px] max-w-[400px]
        animate-fade-in-up motion-reduce:animate-none relative overflow-hidden`}
    >
      <div className="flex-1">
        {item.title && <div className="font-semibold text-sm mb-0.5">{item.title}</div>}
        <div className="text-sm">{item.message}</div>
      </div>
      <button
        onClick={() => onDismiss(item.id)}
        aria-label="关闭"
        className="p-1 rounded hover:bg-white/20 transition-colors cursor-pointer"
      >
        <X size={16} weight="bold" aria-hidden="true" />
      </button>
      {duration !== null && (
        <div
          data-testid="toast-progress"
          aria-hidden="true"
          className="absolute bottom-0 left-0 h-0.5 bg-white/30 animate-toast-progress"
          style={{ animationDuration: `${duration}ms` }}
        />
      )}
    </div>
  );
}

export function ToastContainer() {
  const ctx = useContext(ToastContext);
  if (!ctx) return null;

  const { toasts, remove } = ctx;

  // 响应式定位：移动端底部居中（避免遮挡顶部内容），桌面端 top-right（不遮挡操作区）
  return (
    <div className="fixed bottom-4 left-1/2 -translate-x-1/2 md:bottom-auto md:top-4 md:right-4 md:left-auto md:translate-x-0 z-[100] flex flex-col gap-2">
      {toasts.map((t) => (
        <ToastEntry key={t.id} item={t} onDismiss={remove} />
      ))}
    </div>
  );
}
