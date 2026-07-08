import { api } from "./client";

interface LoginData {
  access_token: string;
  refresh_token: string;
}

export async function login(email: string, password: string): Promise<LoginData> {
  const data = await api.post("/api/v1/auth/login", { email, password }) as LoginData;
  localStorage.setItem("access_token", data.access_token);
  localStorage.setItem("refresh_token", data.refresh_token);
  return data;
}

export async function register(
  username: string,
  email: string,
  password: string,
  password_confirm: string
) {
  return api.post("/api/v1/auth/register", {
    username,
    email,
    password,
    password_confirm,
  });
}

export function logout() {
  localStorage.removeItem("access_token");
  localStorage.removeItem("refresh_token");
}
