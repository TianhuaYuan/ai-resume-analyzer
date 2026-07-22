import {
  createContext,
  useContext,
  useState,
  useCallback,
  useEffect,
  useRef,
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

// ── Auto-dismiss timing ──

const AUTO_DISMISS_MS: Record<ToastType, number> = {
  success: 3000,
  error: 5000,
  info: 4000,
};

const MAX_TOASTS = 3;

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

  return (
    <ToastContext.Provider value={{ success, error, info, toasts, remove }}>
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
  success: "bg-emerald-500",
  error: "bg-red-500",
  info: "bg-blue-500",
};

function ToastEntry({ item, onDismiss }: { item: ToastItem; onDismiss: (id: number) => void }) {
  useEffect(() => {
    const timer = setTimeout(() => onDismiss(item.id), AUTO_DISMISS_MS[item.type]);
    return () => clearTimeout(timer);
  }, [item, onDismiss]);

  return (
    <div
      role="alert"
      className={`${BG_CLASS[item.type]} text-white px-4 py-3 rounded-lg shadow-lg
        flex items-center justify-between gap-3 min-w-[280px] max-w-[400px]
        animate-fade-in-up motion-reduce:animate-none`}
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
    </div>
  );
}

export function ToastContainer() {
  const ctx = useContext(ToastContext);
  if (!ctx) return null;

  const { toasts, remove } = ctx;

  return (
    <div className="fixed top-4 right-4 z-[100] flex flex-col gap-2">
      {toasts.map((t) => (
        <ToastEntry key={t.id} item={t} onDismiss={remove} />
      ))}
    </div>
  );
}