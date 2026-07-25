import { describe, it, expect } from "vitest";
import { computeSessionWarning } from "./sessionWarning";

const WARNING_BEFORE_SECONDS = 300; // 5 分钟
const WARNING_BEFORE_MS = WARNING_BEFORE_SECONDS * 1000;

describe("computeSessionWarning", () => {
  it("已过期 → expired", () => {
    const exp = 2_000_000;
    const now = 2_001_000;
    const result = computeSessionWarning(exp, now, WARNING_BEFORE_SECONDS);
    expect(result.kind).toBe("expired");
  });

  it("在预警窗口内 → warning，返回剩余秒数", () => {
    const exp = 2_000_000;
    const now = exp - 5_000; // 距过期 5 秒，在预警窗口（<300s）
    const result = computeSessionWarning(exp, now, WARNING_BEFORE_SECONDS);
    expect(result.kind).toBe("warning");
    expect(result.remainingSeconds).toBe(5);
  });

  it("预警窗口外 → schedule，返回到预警点的延迟", () => {
    const exp = 2_000_000;
    const now = 0;
    const result = computeSessionWarning(exp, now, WARNING_BEFORE_SECONDS);
    expect(result.kind).toBe("schedule");
    // delay = warningAt - now = (exp - warningBeforeMs) - 0
    expect(result.delayMs).toBe(exp - WARNING_BEFORE_MS);
  });

  it("恰好到预警点 → warning", () => {
    const exp = 2_000_000;
    const now = exp - WARNING_BEFORE_MS; // 恰好在预警点
    const result = computeSessionWarning(exp, now, WARNING_BEFORE_SECONDS);
    expect(result.kind).toBe("warning");
    expect(result.remainingSeconds).toBe(WARNING_BEFORE_SECONDS);
  });
});
