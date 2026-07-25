import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, waitFor, act, screen } from "@testing-library/react";
import { AuthProvider, useAuth } from "./AuthContext";

// ── 构造一个未过期的 fake JWT ──
// payload: { sub, username, email, exp(未来 1 小时) }
function makeFakeToken(expSecondsFromNow = 3600): string {
  const header = { alg: "HS256", typ: "JWT" };
  const payload = {
    sub: 42,
    username: "tester",
    email: "tester@example.com",
    exp: Math.floor(Date.now() / 1000) + expSecondsFromNow,
  };
  const b64obj = (o: unknown) => btoa(JSON.stringify(o));
  return `${b64obj(header)}.${b64obj(payload)}.signature`;
}

// 把 user.username 渲染到 DOM，便于用 screen 查询
function UserLabel() {
  const auth = useAuth();
  return <div data-testid="user-label">{auth.user?.username ?? "GUEST"}</div>;
}

function renderWithProvider() {
  return render(
    <AuthProvider>
      <UserLabel />
    </AuthProvider>
  );
}

describe("AuthContext 多 Tab 登出同步 (P2-17)", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("access_token 被其他 Tab 移除时，当前 Tab user 同步置空", async () => {
    const token = makeFakeToken(3600);
    localStorage.setItem("access_token", token);

    renderWithProvider();

    // 初始加载后应显示 tester
    await waitFor(() => {
      expect(screen.getByTestId("user-label").textContent).toBe("tester");
    });

    // 模拟另一个 Tab 登出：触发 storage 事件，newValue 为 null
    await act(async () => {
      window.dispatchEvent(
        new StorageEvent("storage", {
          key: "access_token",
          newValue: null,
          oldValue: token,
          storageArea: localStorage,
        })
      );
    });

    // 当前 Tab 应该感知到登出
    await waitFor(() => {
      expect(screen.getByTestId("user-label").textContent).toBe("GUEST");
    });
  });

  it("access_token 被其他 Tab 替换为空串时，当前 Tab user 同步置空", async () => {
    const token = makeFakeToken(3600);
    localStorage.setItem("access_token", token);

    renderWithProvider();

    await waitFor(() => {
      expect(screen.getByTestId("user-label").textContent).toBe("tester");
    });

    await act(async () => {
      window.dispatchEvent(
        new StorageEvent("storage", {
          key: "access_token",
          newValue: "",
          oldValue: token,
          storageArea: localStorage,
        })
      );
    });

    await waitFor(() => {
      expect(screen.getByTestId("user-label").textContent).toBe("GUEST");
    });
  });

  it("其他 key 的 storage 事件不影响登录状态", async () => {
    const token = makeFakeToken(3600);
    localStorage.setItem("access_token", token);

    renderWithProvider();

    await waitFor(() => {
      expect(screen.getByTestId("user-label").textContent).toBe("tester");
    });

    await act(async () => {
      window.dispatchEvent(
        new StorageEvent("storage", {
          key: "some_other_key",
          newValue: "whatever",
          oldValue: null,
          storageArea: localStorage,
        })
      );
    });

    expect(screen.getByTestId("user-label").textContent).toBe("tester");
  });
});
