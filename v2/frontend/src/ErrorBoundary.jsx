import React from "react";

/** Błąd widoku pokazuje komunikat z przyciskiem odświeżenia zamiast białego ekranu. */
export default class ErrorBoundary extends React.Component {
  constructor(props) { super(props); this.state = { error: null }; }
  static getDerivedStateFromError(error) { return { error }; }
  componentDidCatch(error, info) { console.error("[ASOLAR v2]", error, info?.componentStack); }
  render() {
    if (!this.state.error) return this.props.children;
    return <div className="card alert error rescue-screen full" role="alert"><h2>Aplikacja napotkała błąd</h2><p>{String(this.state.error?.message || this.state.error)}</p><p>Dane budów są bezpieczne na serwerze.</p>
      <div className="card-actions"><button className="primary" onClick={() => window.location.reload()}>Odśwież aplikację</button><button className="secondary" onClick={() => this.setState({ error: null })}>Spróbuj ponownie</button></div></div>;
  }
}
