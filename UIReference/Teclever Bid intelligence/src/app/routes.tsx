import { createBrowserRouter } from "react-router";
import { Login } from "./pages/Login";
import { Dashboard } from "./pages/Dashboard";
import { PortalBids } from "./pages/PortalBids";
import { BidDetail } from "./pages/BidDetail";
import { ActivityLog } from "./pages/ActivityLog";
import { Layout } from "./components/Layout";

export const router = createBrowserRouter([
  {
    path: "/login",
    Component: Login,
  },
  {
    path: "/",
    Component: Layout,
    children: [
      { index: true, Component: Dashboard },
      { path: "portal/:portalId", Component: PortalBids },
      { path: "bid/:bidId", Component: BidDetail },
      { path: "activity", Component: ActivityLog },
    ],
  },
]);
