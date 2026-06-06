import { createRoot } from "react-dom/client";
import App from "./app/App.tsx";
import "./styles/index.css";

async function enableMocking() {
  if (import.meta.env.VITE_ENABLE_MSW !== "true") return;
  const { worker } = await import("./mocks/browser");
  await worker.start({ onUnhandledRequest: "bypass" });
}

enableMocking().then(() => {
  createRoot(document.getElementById("root")!).render(<App />);
});
