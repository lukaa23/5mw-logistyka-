/* Wspólne drobne elementy interfejsu i formatowanie (pl-PL). */
import React from "react";

export const today = () => new Date().toISOString().slice(0, 10);
export const uid = () => crypto.randomUUID?.() || `${Date.now()}-${Math.random()}`;
export const fmt = value => { if (!value) return "—"; const date = new Date(value); if (Number.isNaN(date.getTime())) return "—"; return new Intl.DateTimeFormat("pl-PL", { dateStyle: "medium", timeStyle: String(value).includes("T") ? "short" : undefined }).format(date); };
export const canWrite = user => user?.role === "kierownik" || user?.role === "brygadzista";
export const pct = (value, total) => total ? Math.round(value / total * 100) : 0;
export const qty = value => new Intl.NumberFormat("pl-PL", { maximumFractionDigits: 2 }).format(Number(value || 0));
export function PageHead({ eyebrow, title, children }) { return <div className="page-head"><div><p className="eyebrow">{eyebrow}</p><h1>{title}</h1></div><div className="head-actions">{children}</div></div>; }
export function Empty({ children }) { return <div className="empty"><span>◇</span><p>{children}</p></div>; }
export function Loader() { return <div className="loading"><i /><span>Ładowanie danych…</span></div>; }
export function Progress({ value }) { return <div className="progress"><i style={{ width: `${Math.min(100, Math.max(0, value))}%` }} /></div>; }
