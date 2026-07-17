import { describe, it, expect } from "vitest";
import { safeDecodeJwt } from "./AuthContext";

function makeJwt(payload: Record<string, unknown>, expired = false): string {
  const p = expired
    ? { ...payload, exp: Math.floor(Date.now() / 1000) - 10 }
    : payload;
  const b64 = (obj: unknown) => btoa(JSON.stringify(obj));
  return `${b64("h")}.${b64(p)}.${b64("s")}`;
}

describe("safeDecodeJwt (H9)", () => {
  it("正常 token 解出 payload", () => {
    const token = makeJwt({ sub: "7", username: "alice", email: "a@x.com" });
    expect(safeDecodeJwt(token)).toMatchObject({ sub: "7", username: "alice" });
  });

  it("缺段 token 返回 null 而非抛异常（避免 atob(undefined) 崩溃）", () => {
    expect(safeDecodeJwt("not.a.jwt")).toBeNull(); // 2 段
    expect(safeDecodeJwt("garbage")).toBeNull(); // 0 段
  });

  it("非法 base64 payload 返回 null 而非抛异常", () => {
    expect(safeDecodeJwt("a.!!!.c")).toBeNull();
  });

  it("非法 JSON payload 返回 null 而非抛异常", () => {
    expect(safeDecodeJwt(`${btoa("h")}.${btoa("{bad")}.${btoa("s")}`)).toBeNull();
  });
});
