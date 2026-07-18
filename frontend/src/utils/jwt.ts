interface JwtPayload {
  sub?: string | number;
  username?: string;
  email?: string;
  exp?: number;
}

/**
 * H9：安全解码 JWT。任何异常（token 缺段、base64 非法、JSON 损坏）都返回 null，
 * 绝不让 atob/JSON.parse 抛出的异常冒泡到 React 渲染或登录流程里造成白屏。
 */
export function safeDecodeJwt(token: string): JwtPayload | null {
  try {
    const parts = token.split(".");
    if (parts.length !== 3) return null;
    return JSON.parse(atob(parts[1])) as JwtPayload;
  } catch {
    return null;
  }
}
