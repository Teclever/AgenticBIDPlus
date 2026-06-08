import { createBrowserRouter } from "react-router";
import { Login } from "./pages/Login";
import { Dashboard } from "./pages/Dashboard";
import { PortalBids } from "./pages/PortalBids";
import { BidDetail } from "./pages/BidDetail";
import { ActivityLog } from "./pages/ActivityLog";
import { Notifications } from "./pages/Notifications";
import { Layout } from "./components/Layout";
import { AuthGuard } from "./components/AuthGuard";

export const router = createBrowserRouter([
  {
    path: "/login",
    Component: Login,
  },
  {
    path: "/",
    Component: Layout,
    children: [
      {
        index: true,
        element: (
          <AuthGuard>
            <Dashboard />
          </AuthGuard>
        ),
      },
      {
        path: "portal/:portalId",
        element: (
          <AuthGuard>
            <PortalBids />
          </AuthGuard>
        ),
      },
      {
        path: "portal/:portalId/bid/:bidKey",
        element: (
          <AuthGuard>
            <BidDetail />
          </AuthGuard>
        ),
      },
      {
        path: "activity",
        element: (
          <AuthGuard>
            <ActivityLog />
          </AuthGuard>
        ),
      },
      {
        path: "notifications",
        element: (
          <AuthGuard>
            <Notifications />
          </AuthGuard>
        ),
      },
    ],
  },
]);
