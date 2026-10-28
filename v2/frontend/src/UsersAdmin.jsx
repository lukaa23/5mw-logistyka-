import React, { useState } from "react";
import { api, send } from "./api";
import { AddButton, AsyncButton, Empty, Loader, PageHead, useAskText, useConfirm, useEscape } from "./ui";
import { useLoad } from "./useLoad";

function UserEdit({ item, onSave, onCancel }) {
  const [form, setForm] = useState({ full_name: item.full_name, is_admin: item.is_admin });
  useEscape(onCancel);
  return <form className="user-edit editing" onSubmit={async event => { event.preventDefault(); await onSave(form); }}>
    <label>Imię i nazwisko<input required minLength="2" autoFocus value={form.full_name} onChange={e => setForm(c => ({ ...c, full_name: e.target.value }))} /></label>
    <label className="check-line"><input type="checkbox" checked={form.is_admin} onChange={e => setForm(c => ({ ...c, is_admin: e.target.checked }))} /> Administrator (tworzy budowy i konta, widzi wszystkie budowy)</label>
    <div className="card-actions"><button className="primary">Zapisz</button><button type="button" className="secondary" onClick={onCancel}>Anuluj</button></div>
  </form>;
}

export default function UsersAdmin({ user, notify }) {
  const blank = { username: "", full_name: "", password: "", is_admin: false };
  const { data: users, loading, reload } = useLoad(() => api("/api/users"), []);
  const [form, setForm] = useState(blank);
  const [editingId, setEditingId] = useState(null);
  const [busy, setBusy] = useState(false);
  const confirm = useConfirm();
  const askText = useAskText();
  if (!user.is_admin) return <Empty>Konta zakłada administrator.</Empty>;
  async function update(item, values, message) { try { await send(`/api/users/${item.id}`, "PATCH", values); notify(message); await reload(); return true; } catch (failure) { notify(failure.message, "error"); return false; } }
  async function create(event) {
    event.preventDefault(); setBusy(true);
    try { await send("/api/users", "POST", form); notify(`Konto ${form.username} utworzone — dodaj je do zespołu wybranej budowy`); setForm(blank); await reload(); }
    catch (failure) { notify(failure.message, "error"); } finally { setBusy(false); }
  }
  async function password(item) {
    const value = await askText({ title: `Nowe hasło — ${item.full_name}`, message: "Przekaż hasło osobiście. Dotychczasowe przestanie działać.", input: { label: "Nowe hasło", type: "password", minLength: 8 }, confirmLabel: "Zmień hasło" });
    if (value) await update(item, { password: value }, "Hasło zmienione");
  }
  async function toggle(item) {
    if (item.active && !(await confirm({ title: "Dezaktywować konto?", message: `${item.full_name} nie zaloguje się do żadnej budowy. Wpisy pozostaną.`, danger: true, confirmLabel: "Dezaktywuj" }))) return;
    await update(item, { active: !item.active }, item.active ? "Konto dezaktywowane" : "Konto aktywne");
  }
  return <><PageHead eyebrow="ADMINISTRACJA" title="Konta"><AddButton target="user-form">Nowe konto</AddButton></PageHead>
    <div className="split"><section className="card">{loading && !users ? <Loader /> : (users || []).map(item => <div className={`user-row ${item.active ? "" : "inactive"}`} key={item.id} data-testid="user-row">
      <div className="avatar">{item.full_name.split(" ").map(x => x[0]).slice(0, 2).join("")}</div>
      {editingId === item.id ? <UserEdit item={item} onCancel={() => setEditingId(null)} onSave={async values => { if (await update(item, values, "Zapisano konto")) setEditingId(null); }} />
        : <><div><strong>{item.full_name}</strong><small>@{item.username}{item.is_admin ? " · administrator" : ""}{item.active ? "" : " · nieaktywne"}</small></div>
          <div className="card-actions"><button type="button" onClick={() => setEditingId(item.id)}>Edytuj</button><button type="button" onClick={() => password(item)}>Zmień hasło</button>{item.id !== user.id && <AsyncButton className={item.active ? "danger-button" : "secondary"} onClick={() => toggle(item)}>{item.active ? "Dezaktywuj" : "Aktywuj"}</AsyncButton>}</div></>}
    </div>)}<p className="hint">Dostęp do budów i role (kierownik / brygadzista) ustawia się w zakładce „Zespół” każdej budowy.</p></section>
      <form id="user-form" className="card" onSubmit={create}><h2>Nowe konto</h2>
        <label>Imię i nazwisko<input required minLength="2" value={form.full_name} onChange={e => setForm(c => ({ ...c, full_name: e.target.value }))} /></label>
        <label>Login<input required pattern="[A-Za-z0-9._-]+" minLength="3" value={form.username} onChange={e => setForm(c => ({ ...c, username: e.target.value }))} /></label>
        <label>Hasło<input type="password" required minLength="8" autoComplete="new-password" value={form.password} onChange={e => setForm(c => ({ ...c, password: e.target.value }))} /></label>
        <label className="check-line"><input type="checkbox" checked={form.is_admin} onChange={e => setForm(c => ({ ...c, is_admin: e.target.checked }))} /> Administrator</label>
        <button className="primary wide" disabled={busy}>{busy ? "Tworzenie…" : "Utwórz konto"}</button>
      </form></div></>;
}
