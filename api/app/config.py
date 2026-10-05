"""Konfiguration. Alles ueber Umgebungsvariablen, nichts fest im Code."""
import os


def _bool(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).strip().lower() in ("1", "true", "yes", "ja")


class Settings:
    # --- Datenbank ---------------------------------------------------------
    # Die Anwendung verbindet sich als eingeschraenkte Rolle. Nur so greifen
    # die Zeilen-Rechte in der Datenbank.
    app_dsn: str = os.getenv(
        "APP_DATABASE_URL",
        "postgresql://kg_app:kg_app_pw@localhost:5432/knowledge_guard",
    )
    # Eigentuemer-Verbindung: ausschliesslich fuer Einrichtung und Beispieldaten.
    owner_dsn: str = os.getenv(
        "OWNER_DATABASE_URL",
        "postgresql://kg_owner:kg_owner_pw@localhost:5432/knowledge_guard",
    )

    # --- Anmeldung ---------------------------------------------------------
    token_secret: str = os.getenv("TOKEN_SECRET", "nur-fuer-die-vorfuehrung-aendern")
    token_ttl_seconds: int = int(os.getenv("TOKEN_TTL_SECONDS", "28800"))

    # --- Vektoren ----------------------------------------------------------
    embedding_dim: int = 1536
    # auto = OpenAI, wenn ein Schluessel da ist, sonst der eingebaute
    # Textvergleich. Damit laeuft die Vorfuehrung auch ohne jeden Schluessel.
    embedding_provider: str = os.getenv("EMBEDDING_PROVIDER", "auto").strip().lower()
    openai_embedding_model: str = os.getenv(
        "OPENAI_EMBEDDING_MODEL", "text-embedding-3-small"
    )

    # --- Sprachmodell ------------------------------------------------------
    llm_provider: str = os.getenv("LLM_PROVIDER", "auto").strip().lower()
    anthropic_api_key: str = os.getenv("ANTHROPIC_API_KEY", "").strip()
    anthropic_model: str = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-5-5")
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "").strip()
    openai_model: str = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    llm_timeout: float = float(os.getenv("LLM_TIMEOUT", "60"))

    # --- Verhalten ---------------------------------------------------------
    top_k: int = int(os.getenv("TOP_K", "5"))
    # Die Zahl gesperrter Treffer anzeigen. In sehr strengen Umgebungen ist
    # schon eine Zahl ein Hinweis -- dann hier abschalten.
    show_blocked_count: bool = _bool("SHOW_BLOCKED_COUNT", True)
    grant_days_default: int = int(os.getenv("GRANT_DAYS_DEFAULT", "14"))

    def resolved_embedding_provider(self) -> str:
        if self.embedding_provider == "auto":
            return "openai" if self.openai_api_key else "local"
        return self.embedding_provider

    def resolved_llm_provider(self) -> str:
        if self.llm_provider == "auto":
            if self.anthropic_api_key:
                return "anthropic"
            if self.openai_api_key:
                return "openai"
            return "none"
        return self.llm_provider


settings = Settings()
