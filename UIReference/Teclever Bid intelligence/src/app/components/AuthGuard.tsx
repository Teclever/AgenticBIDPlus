import { useEffect } from "react";
import { useNavigate } from "react-router";
import { useAuth } from "../context/AuthContext";

export function AuthGuard({ children }: { children: React.ReactNode }) {
  const { user, loading } = useAuth();
  const navigate = useNavigate();

  useEffect(() => {
    if (!loading && !user) {
      navigate("/login", { replace: true });
    }
  }, [loading, user, navigate]);

  if (loading) {
    return (
      <div className="min-h-[50vh] flex items-center justify-center text-gray-500">
        Loading…
      </div>
    );
  }

  if (!user) return null;

  return <>{children}</>;
}
