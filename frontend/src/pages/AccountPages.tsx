import { ArrowRight, LockKeyhole, LogOut, Sparkles } from "lucide-react";
import { useState } from "react";
import type { FormEvent, ReactNode } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext";

function AccountLayout({ children, title, intro, mode }: { children: ReactNode; title: string; intro: string; mode: "login" | "register" }) {
  return (
    <section className="page-shell account-page">
      <div className="account-art">
        <div className="account-art-inner"><span className="eyebrow account-brand-label">LittleLeaf membership</span><div className="account-art-shape"><span>✳</span></div><p>Good to have<br /><em>you here.</em></p><span className="account-art-caption">YOUR CORNER OF THE EVERYDAY</span></div>
      </div>
      <div className="account-form-panel">
        <span className="eyebrow">{mode === "login" ? "Welcome back" : "A place to call yours"}</span>
        <h1>{title}</h1>{intro && <p className="account-intro">{intro}</p>}
        {children}
        <div className="account-switch">{mode === "login" ? "New around here?" : "Already have an account?"} <Link to={mode === "login" ? "/register" : "/login"}>{mode === "login" ? "Create an account" : "Sign in"} <ArrowRight size={14} /></Link></div>
      </div>
    </section>
  );
}

function accountError(reason: unknown): string {
  return reason instanceof Error ? reason.message : "The request could not be completed. Please try again.";
}

export function LoginPage() {
  const { login, logout, user, isLoading } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState("");
  const [loginNotice] = useState(() => {
    const state = location.state as { registered?: boolean; sessionExpired?: boolean } | null;
    if (state?.sessionExpired) return "Your previous sign-in expired. Sign in again to continue.";
    return state?.registered ? "Your account is ready. Sign in to continue." : "";
  });

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setError("");
    setIsSubmitting(true);
    const form = new FormData(event.currentTarget);
    try {
      await login({ email: String(form.get("email")).trim(), password: String(form.get("password")) });
      const state = location.state as { from?: { pathname?: string } } | null;
      const destination = state?.from?.pathname?.startsWith("/") ? state.from.pathname : "/";
      navigate(destination, { replace: true });
    } catch (reason) {
      setError(accountError(reason));
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <AccountLayout mode="login" title="Come on in." intro="">
      {user ? <div className="signed-in-card"><span className="eyebrow">Signed in</span><strong>{user.email}</strong><button className="button button-outline" type="button" onClick={() => logout()}><LogOut size={15} /> Sign out</button></div> : <>
        {loginNotice && <p className="form-feedback" role="status">{loginNotice}</p>}
        <form className="form-stack" onSubmit={submit}>
          <label>Email address<input type="email" name="email" autoComplete="email" placeholder="you@example.com" maxLength={255} required disabled={isLoading || isSubmitting} /></label>
          <label>Password<input type="password" name="password" autoComplete="current-password" placeholder="Your password" minLength={4} maxLength={128} required disabled={isLoading || isSubmitting} /></label>
          {error && <p className="form-feedback form-error" role="alert">{error}</p>}
          <button className="button button-dark form-submit" type="submit" disabled={isLoading || isSubmitting}><LockKeyhole size={16} /> {isSubmitting ? "Signing in…" : "Sign in"}</button>
        </form>
      </>}
    </AccountLayout>
  );
}

export function RegisterPage() {
  const { register } = useAuth();
  const navigate = useNavigate();
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setError("");
    setSuccess("");
    const registrationForm = event.currentTarget;
    const form = new FormData(registrationForm);
    const name = String(form.get("name")).trim();
    const email = String(form.get("email")).trim();
    const password = String(form.get("password"));
    const confirmPassword = String(form.get("confirmPassword"));
    if (password !== confirmPassword) {
      setError("The passwords do not match.");
      return;
    }
    setIsSubmitting(true);
    try {
      await register({ name, email, password });
      registrationForm.reset();
      setSuccess("Account created. Please sign in; registration does not sign you in automatically.");
    } catch (reason) {
      setError(accountError(reason));
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <AccountLayout mode="register" title="Make yourself at home." intro="Join LittleLeaf and make everyday shopping a little easier.">
      <form className="form-stack" onSubmit={submit}>
        <label>Your name<input type="text" name="name" autoComplete="name" placeholder="Name" minLength={1} maxLength={120} required disabled={isSubmitting} /></label>
        <label>Email address<input type="email" name="email" autoComplete="email" placeholder="you@example.com" maxLength={255} required disabled={isSubmitting} /></label>
        <label>Create password<input type="password" name="password" autoComplete="new-password" placeholder="At least 4 characters" minLength={4} maxLength={128} required disabled={isSubmitting} /></label>
        <label>Confirm password<input type="password" name="confirmPassword" autoComplete="new-password" placeholder="Enter it again" minLength={4} maxLength={128} required disabled={isSubmitting} /></label>
        {error && <p className="form-feedback form-error" role="alert">{error}</p>}
        {success && <p className="form-feedback" role="status">{success} <button className="inline-link-button" type="button" onClick={() => navigate("/login", { replace: true, state: { registered: true } })}>Go to sign in</button></p>}
        <button className="button button-dark form-submit" type="submit" disabled={isSubmitting}><Sparkles size={16} /> {isSubmitting ? "Creating account…" : "Create account"}</button>
      </form>
    </AccountLayout>
  );
}
