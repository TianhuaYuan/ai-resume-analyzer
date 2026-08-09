import { createContext, useContext, useEffect, useState, useMemo, useCallback, type ReactNode } from "react";

/** 用户可选的 4 主题模式 */
export type Theme = "light" | "dark" | "system" | "oled";

/** 实际写入 <html data-theme> 的有效值 */
type EffectiveTheme = "light" | "dark" | "oled-dark";

/** UI Scale 可调范围（对齐 Open WebUI 的 --app-text-scale） */
export const TEXT_SCALE_MIN = 1.0;
export const TEXT_SCALE_MAX = 1.5;
const TEXT_SCALE_KEY = "ui-text-scale";

interface ThemeContextType {
  /** 用户当前选择的主题模式 */
  theme: Theme;
  /** 设置主题模式（light/dark/system/oled） */
  setTheme: (t: Theme) => void;
  /** 兼容旧调用：循环切换（light→dark→system→oled） */
  toggleTheme: () => void;
  /** 界面缩放系数（1.0–1.5，作用于 html font-size → rem 等比缩放） */
  textScale: number;
  setTextScale: (v: number) => void;
  /** 高对比无障碍模式（html.high-contrast class，见 index.css） */
  highContrast: boolean;
  setHighContrast: (v: boolean) => void;
}

const ThemeContext = createContext<ThemeContextType | undefined>(undefined);

const THEME_CYCLE: Theme[] = ["light", "dark", "system", "oled"];

function clampScale(v: number): number {
  if (Number.isNaN(v)) return 1;
  return Math.min(TEXT_SCALE_MAX, Math.max(TEXT_SCALE_MIN, v));
}

function isValidTheme(v: string | null): v is Theme {
  return v === "light" || v === "dark" || v === "system" || v === "oled";
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [theme, setThemeState] = useState<Theme>(() => {
    const saved = localStorage.getItem("theme");
    return isValidTheme(saved) ? saved : "light";
  });

  // P0 UI Scale：从 localStorage 恢复缩放系数，clamp 到合法区间
  const [textScale, setTextScaleState] = useState<number>(() => {
    const saved = localStorage.getItem(TEXT_SCALE_KEY);
    return saved ? clampScale(Number(saved)) : 1;
  });

  // P2 高对比模式：html.high-contrast class
  const [highContrast, setHighContrastState] = useState<boolean>(() => {
    return localStorage.getItem("high-contrast") === "1";
  });

  // 主题解析：system 跟随系统（prefers-color-scheme），oled 映射 oled-dark
  const resolveTheme = useCallback((t: Theme): EffectiveTheme => {
    if (t === "system") {
      const dark = window.matchMedia?.("(prefers-color-scheme: dark)").matches;
      return dark ? "dark" : "light";
    }
    if (t === "oled") return "oled-dark";
    return t;
  }, []);

  // 应用主题 + system 模式监听系统切换
  useEffect(() => {
    const apply = () => {
      document.documentElement.setAttribute("data-theme", resolveTheme(theme));
      localStorage.setItem("theme", theme);
    };
    apply();

    if (theme === "system") {
      const media = window.matchMedia?.("(prefers-color-scheme: dark)");
      media?.addEventListener("change", apply);
      return () => media?.removeEventListener("change", apply);
    }
  }, [theme, resolveTheme]);

  // UI Scale：写入 CSS 变量 --app-text-scale → html font-size 缩放（见 index.css）
  useEffect(() => {
    document.documentElement.style.setProperty("--app-text-scale", String(textScale));
    localStorage.setItem(TEXT_SCALE_KEY, String(textScale));
  }, [textScale]);

  // 高对比：toggle html.high-contrast class（CSS 变量覆盖在 index.css）
  useEffect(() => {
    document.documentElement.classList.toggle("high-contrast", highContrast);
    localStorage.setItem("high-contrast", highContrast ? "1" : "0");
  }, [highContrast]);

  const setTheme = useCallback((t: Theme) => setThemeState(t), []);
  const toggleTheme = useCallback(() => {
    setThemeState((prev) => THEME_CYCLE[(THEME_CYCLE.indexOf(prev) + 1) % THEME_CYCLE.length]);
  }, []);
  const setTextScale = useCallback((v: number) => setTextScaleState(clampScale(v)), []);
  const setHighContrast = useCallback((v: boolean) => setHighContrastState(v), []);

  // memoize context value：theme/textScale/highContrast 未变时 value 引用稳定，
  // 避免 ThemeProvider 每次渲染都重建对象 → 所有 useTheme 消费者级联重渲染
  const value = useMemo(
    () => ({
      theme,
      setTheme,
      toggleTheme,
      textScale,
      setTextScale,
      highContrast,
      setHighContrast,
    }),
    [theme, setTheme, toggleTheme, textScale, setTextScale, highContrast, setHighContrast]
  );

  return (
    <ThemeContext.Provider value={value}>
      {children}
    </ThemeContext.Provider>
  );
}

export function useTheme() {
  const ctx = useContext(ThemeContext);
  if (!ctx) throw new Error("useTheme must be used within ThemeProvider");
  return ctx;
}
