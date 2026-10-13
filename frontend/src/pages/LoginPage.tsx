import { useQuery } from "@tanstack/react-query";
import { type FormEvent, useState } from "react";
import { Navigate, useLocation, useNavigate } from "react-router";

import { ApiError } from "../api/client.ts";
import { fetchHealth } from "../api/health.ts";
import { useAuth } from "../auth/context.ts";
import { t } from "../i18n/t.ts";

export function LoginPage() {
  const { login, status } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  if (status === "authenticated") return <Navigate to="/" replace />;

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      await login(email, password);
      const from = (location.state as { from?: string } | null)?.from;
      navigate(from ?? "/", { replace: true });
    } catch (err) {
      setError(err instanceof ApiError && err.status === 401 ? t("login.invalid") : t("login.failed"));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="flex min-h-screen items-center justify-center bg-gray-100 p-4">
      <form
        onSubmit={onSubmit}
        className="flex w-full max-w-md flex-col gap-4 rounded-xl bg-white p-8 shadow"
      >
        <h1 className="text-3xl font-bold text-gray-900">{t("login.title")}</h1>
        <label className="flex flex-col gap-1 text-lg">
          {t("login.email")}
          <input
            type="email"
            autoComplete="username"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            className="rounded-md border border-gray-300 px-3 py-2 text-xl"
          />
        </label>
        <label className="flex flex-col gap-1 text-lg">
          {t("login.password")}
          <input
            type="password"
            autoComplete="current-password"
            required
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className="rounded-md border border-gray-300 px-3 py-2 text-xl"
          />
        </label>
        {error && (
          <p role="alert" className="text-lg text-red-700">
            {error}
          </p>
        )}
        <button
          type="submit"
          disabled={submitting}
          className="rounded-md bg-blue-700 px-4 py-3 text-xl font-semibold text-white disabled:opacity-60"
        >
          {submitting ? t("login.submitting") : t("login.submit")}
        </button>
        <HealthFooter />
      </form>
    </main>
  );
}

/** Step 1's health check, kept as a small footer: is the backend (and its database) up? */
function HealthFooter() {
  const health = useQuery({ queryKey: ["health"], queryFn: () => fetchHealth(), retry: false });
  const unreachable = t("health.unreachable");
  return (
    <p className="text-sm text-gray-500">
      {t("health.status", {
        backend: health.isError ? unreachable : health.data ? "ok" : "…",
        database: health.data?.database ?? (health.isError ? unreachable : "…"),
      })}
    </p>
  );
}
