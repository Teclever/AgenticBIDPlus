import { useState, FormEvent, useEffect } from "react";
import { useNavigate } from "react-router";
import { AlertCircle, Loader2 } from "lucide-react";
import { Button } from "../components/ui/button";
import TecleverLogo from "../../imports/TECLEVER_Logo.jpg";
import { authApi, ApiRequestError } from "../lib/api";
import { useAuth } from "../context/AuthContext";

export function Login() {
  const navigate = useNavigate();
  const { user, refresh } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [rememberMe, setRememberMe] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  useEffect(() => {
    if (user) navigate("/", { replace: true });
  }, [user, navigate]);

  const canSubmit = email.trim() !== "" && password.trim() !== "";

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    if (!canSubmit) return;

    setSubmitting(true);
    setErrorMessage(null);

    try {
      await authApi.login(email.trim(), password, rememberMe);
      try {
        await refresh();
      } catch {
        setErrorMessage("Signed in but session could not be verified. Try again.");
        return;
      }
      navigate("/");
    } catch (err) {
      if (err instanceof ApiRequestError) {
        if (err.code === "invalid_credentials" || err.code === "non_teclever_email") {
          setErrorMessage("Sign in failed. Check your Teclever email and password.");
        } else {
          setErrorMessage("Unable to reach the server. Try again later.");
        }
      } else if (err instanceof TypeError) {
        setErrorMessage("Unable to reach the server. Try again later.");
      } else {
        setErrorMessage("Sign in failed. Check your Teclever email and password.");
      }
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="min-h-screen bg-gradient-to-br from-blue-50 to-indigo-100 flex items-center justify-center p-4">
      <div className="w-full max-w-md">
        <div className="bg-white rounded-2xl shadow-xl p-8">
          <div className="flex flex-col items-center mb-8">
            <div className="mb-4">
              <img src={TecleverLogo} alt="Teclever" className="h-16" />
            </div>
            <h1 className="text-xl font-semibold text-gray-900 mt-2">Bid Intelligence Platform</h1>
            <p className="text-sm text-gray-600 mt-1">Sign in to your account</p>
          </div>

          {errorMessage && (
            <div className="mb-6 p-4 bg-red-50 border border-red-200 rounded-lg flex items-start gap-3">
              <AlertCircle className="w-5 h-5 text-red-600 shrink-0 mt-0.5" />
              <p className="flex-1 text-sm text-red-800">{errorMessage}</p>
              <button
                onClick={() => setErrorMessage(null)}
                className="text-red-400 hover:text-red-600"
                aria-label="Dismiss"
              >
                <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </div>
          )}

          <form onSubmit={handleSubmit} className="space-y-6">
            <div>
              <label htmlFor="email" className="block text-sm font-medium text-gray-700 mb-2">
                Teclever email
              </label>
              <input
                id="email"
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent transition-all"
                placeholder="you@teclever.com"
                autoComplete="email"
              />
            </div>

            <div>
              <label htmlFor="password" className="block text-sm font-medium text-gray-700 mb-2">
                Password
              </label>
              <input
                id="password"
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent transition-all"
                placeholder="••••••••"
                autoComplete="current-password"
              />
            </div>

            <label className="flex items-center gap-2 cursor-pointer">
              <input
                type="checkbox"
                checked={rememberMe}
                onChange={(e) => setRememberMe(e.target.checked)}
                className="w-4 h-4 text-blue-600 border-gray-300 rounded focus:ring-blue-500"
              />
              <span className="text-sm text-gray-700">Remember me</span>
            </label>

            <Button
              type="submit"
              size="lg"
              variant="primary"
              className="w-full gap-2"
              disabled={!canSubmit || submitting}
            >
              {submitting ? (
                <><Loader2 className="w-4 h-4 animate-spin" />Signing in…</>
              ) : (
                "Sign In"
              )}
            </Button>
          </form>
        </div>
      </div>
    </div>
  );
}
