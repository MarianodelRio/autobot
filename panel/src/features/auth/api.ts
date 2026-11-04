import { api, unwrap } from "@/api/client";

export interface LoginPayload {
  username: string;
  password: string;
  otp: string;
}

export function fetchCsrf() {
  return unwrap(api.GET("/auth/csrf"));
}

export function login(payload: LoginPayload) {
  return unwrap(api.POST("/auth/login", { body: payload }));
}

export function logout() {
  return unwrap(api.POST("/auth/logout"));
}

export function fetchMe() {
  return unwrap(api.GET("/auth/me"));
}
