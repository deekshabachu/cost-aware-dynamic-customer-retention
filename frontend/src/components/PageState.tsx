import { AlertCircle, LoaderCircle } from "lucide-react";
import type { ReactNode } from "react";

export function LoadingState({ label = "Loading" }: { label?: string }) {
  return <div className="state-card"><LoaderCircle className="spin" size={20} /><span>{label}…</span></div>;
}

export function ErrorState({ message, retry }: { message: string; retry?: () => void }) {
  return (
    <div className="state-card state-error" role="alert">
      <AlertCircle size={19} /><span>{message}</span>
      {retry && <button className="text-button" onClick={retry}>Try again</button>}
    </div>
  );
}

export function DemoNotice({ children }: { children: ReactNode }) {
  return <div className="demo-notice"><span className="notice-dot" />{children}</div>;
}
