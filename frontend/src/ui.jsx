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

/* ---------- Okno potwierdzenia / pytania (zamiast window.confirm i window.prompt) ---------- */

const DialogContext = React.createContext(null);

/**
 * Jedno okno dialogowe na całą aplikację. Escape = Anuluj, Enter = Potwierdź.
 * Opcje: title, message, confirmLabel, cancelLabel, danger, requireText (trzeba przepisać tekst),
 * input: { label, type, minLength, placeholder } — wtedy wynik to wpisany tekst albo null.
 */
export function DialogProvider({ children }) {
  const [dialog, setDialog] = React.useState(null);
  const open = React.useCallback(options => new Promise(resolve => setDialog({ ...options, resolve })), []);
  const close = value => { dialog?.resolve(value); setDialog(null); };
  return <DialogContext.Provider value={open}>{children}{dialog && <Dialog dialog={dialog} onClose={close} />}</DialogContext.Provider>;
}

function Dialog({ dialog, onClose }) {
  const [text, setText] = React.useState("");
  const confirmRef = React.useRef(null);
  const inputRef = React.useRef(null);
  const asksText = !!dialog.input || !!dialog.requireText;
  const minLength = dialog.input?.minLength || 0;
  const valid = dialog.requireText ? text.trim() === dialog.requireText : !dialog.input || text.length >= minLength;
  React.useEffect(() => { (asksText ? inputRef.current : confirmRef.current)?.focus(); }, []);
  const cancel = () => onClose(dialog.input ? null : false);
  const accept = () => { if (valid) onClose(dialog.input ? text : true); };
  function onKeyDown(event) {
    if (event.key === "Escape") { event.preventDefault(); event.stopPropagation(); cancel(); }
    else if (event.key === "Enter" && event.target.tagName !== "TEXTAREA" && event.target.tagName !== "BUTTON") { event.preventDefault(); accept(); }
  }
  return <div className="dialog-overlay" onMouseDown={event => { if (event.target === event.currentTarget) cancel(); }}>
    <div className={`card dialog ${dialog.danger ? "danger" : ""}`} role="alertdialog" aria-modal="true" aria-labelledby="asolar-dialog-title" onKeyDown={onKeyDown}>
      <h2 id="asolar-dialog-title">{dialog.title}</h2>
      {dialog.message && <p className="dialog-message">{dialog.message}</p>}
      {dialog.requireText && <label>Wpisz <b>{dialog.requireText}</b>, aby potwierdzić<input ref={inputRef} value={text} onChange={event => setText(event.target.value)} autoComplete="off" /></label>}
      {dialog.input && <label>{dialog.input.label}<input ref={inputRef} type={dialog.input.type || "text"} value={text} placeholder={dialog.input.placeholder || ""} autoComplete={dialog.input.type === "password" ? "new-password" : "off"} onChange={event => setText(event.target.value)} />{minLength ? <small className="hint">Minimum {minLength} znaków.</small> : null}</label>}
      <div className="card-actions dialog-actions">
        <button type="button" className="secondary" onClick={cancel}>{dialog.cancelLabel || "Anuluj"}</button>
        <button type="button" ref={confirmRef} className={dialog.danger ? "danger-button solid" : "primary"} disabled={!valid} onClick={accept}>{dialog.confirmLabel || (dialog.danger ? "Usuń" : "OK")}</button>
      </div>
      <small className="hint dialog-keys">Enter — potwierdź · Esc — anuluj</small>
    </div>
  </div>;
}

/** Potwierdzenie akcji: zwraca Promise<boolean>. Bez DialogProvider używa window.confirm. */
export function useConfirm() {
  const open = React.useContext(DialogContext);
  return React.useCallback(options => (open ? open(options) : Promise.resolve(window.confirm([options.title, options.message].filter(Boolean).join("\n\n")))), [open]);
}

/** Pytanie o tekst (np. nowe hasło): zwraca Promise<string|null>. */
export function useAskText() {
  const open = React.useContext(DialogContext);
  return React.useCallback(options => (open ? open(options) : Promise.resolve(window.prompt(options.title) || null)), [open]);
}

/* ---------- Przycisk ze stanem ładowania ---------- */

/** Blokuje ponowne kliknięcie i pokazuje stan „…” do zakończenia akcji asynchronicznej. */
export function AsyncButton({ onClick, busyLabel, children, className = "secondary", disabled, type = "button", ...rest }) {
  const [busy, setBusy] = React.useState(false);
  const mounted = React.useRef(true);
  React.useEffect(() => () => { mounted.current = false; }, []);
  async function handle(event) {
    if (busy) return;
    setBusy(true);
    try { await onClick?.(event); } finally { if (mounted.current) setBusy(false); }
  }
  return <button type={type} className={`${className} ${busy ? "is-busy" : ""}`} disabled={disabled || busy} aria-busy={busy} onClick={handle} {...rest}>{busy ? (busyLabel || "Trwa…") : children}</button>;
}

/** Escape anuluje edycję (formularz, panel). */
export function useEscape(handler, active = true) {
  React.useEffect(() => {
    if (!active) return undefined;
    const listener = event => { if (event.key === "Escape" && !event.defaultPrevented && !document.querySelector(".dialog-overlay")) handler(event); };
    window.addEventListener("keydown", listener);
    return () => window.removeEventListener("keydown", listener);
  }, [handler, active]);
}

/** Przewija do formularza „Dodaj nowy” i ustawia kursor w pierwszym polu. */
export function focusForm(id) {
  const form = document.getElementById(id);
  if (!form) return;
  form.scrollIntoView?.({ behavior: "smooth", block: "start" });
  setTimeout(() => form.querySelector("input:not([type=hidden]):not([type=file]), select, textarea")?.focus({ preventScroll: true }), 250);
}

/** Przycisk „+ Dodaj …” w nagłówku strony. */
export function AddButton({ target, children }) {
  return <button type="button" className="primary add-new" onClick={() => focusForm(target)}>+ {children}</button>;
}
