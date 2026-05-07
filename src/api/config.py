"""Configurações da aplicação carregadas de variáveis de ambiente / .env."""

from __future__ import annotations

from typing import List, Literal, Optional

from pydantic_settings import BaseSettings, SettingsConfigDict

ModoStorage = Literal["memoria", "sqlite", "dynamodb"]


class Settings(BaseSettings):
    """Configurações globais da API."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ------------------------------------------------------------------
    # Storage — escolha do backend de persistência
    # ------------------------------------------------------------------
    # "memoria"   = StorageMemoria (dev/testes, sem persistência)
    # "sqlite"    = SQLite local (produção self-hosted EC2)
    # "dynamodb"  = DynamoDB (legado, ainda suportado)
    modo_storage: ModoStorage = "sqlite"

    # Caminho do banco SQLite (relativo ou absoluto)
    sqlite_path: str = "./vagas.db"

    # Compat: se modo_local=True, sobrescreve modo_storage para "memoria".
    # Mantido para não quebrar testes existentes e .env antigos.
    modo_local: bool = False

    # ------------------------------------------------------------------
    # MQTT (broker Mosquitto self-hosted)
    # ------------------------------------------------------------------
    mqtt_host: str = "localhost"
    mqtt_port: int = 1883
    mqtt_user: Optional[str] = None
    mqtt_password: Optional[str] = None
    mqtt_topic: str = "estacionamento/+/vagas"
    mqtt_client_id: str = "estacionamento-worker"

    # ------------------------------------------------------------------
    # AWS (legado — usado só se modo_storage="dynamodb")
    # ------------------------------------------------------------------
    aws_region: str = "sa-east-1"
    aws_profile: str = "default"
    tabela_eventos: str = "vagas_eventos"
    tabela_estado: str = "vagas_estado"

    # ------------------------------------------------------------------
    # API / observabilidade
    # ------------------------------------------------------------------
    cors_origins: str = "*"
    log_level: str = "INFO"

    @property
    def cors_origins_list(self) -> List[str]:
        if self.cors_origins == "*":
            return ["*"]
        return [origin.strip() for origin in self.cors_origins.split(",")]

    @property
    def storage_efetivo(self) -> ModoStorage:
        """Retorna o modo de storage considerando a flag de compat ``modo_local``."""
        if self.modo_local:
            return "memoria"
        return self.modo_storage


# Singleton (settings globais)
_settings: Optional[Settings] = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


def reset_settings() -> None:
    """Útil em testes para forçar releitura do ambiente."""
    global _settings
    _settings = None
