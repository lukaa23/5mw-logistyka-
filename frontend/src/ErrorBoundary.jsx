import React from "react";

/** Błąd jednego widoku pokazuje komunikat zamiast białego ekranu całej aplikacji. */
export default class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { error: null };
  }

  static getDerivedStateFromError(error) {
    return { error };
  }

  componentDidCatch(error, info) {
    console.error("[ASOLAR] Błąd widoku", error, info?.componentStack);
  }

  render() {
    if (!this.state.error) return this.props.children;
    return <div className="card alert error" role="alert">
      <h2>Ten widok napotkał błąd</h2>
      <p>{String(this.state.error?.message || this.state.error)}</p>
      <p>Dane są bezpieczne na serwerze. Przejdź do innej zakładki lub odśwież stronę.</p>
      <button className="secondary" onClick={() => this.setState({ error: null })}>Spróbuj ponownie</button>
    </div>;
  }
}
