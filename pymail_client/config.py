"""Persistência de configuração em arquivo texto (RF-SET-01, RF-SET-02).

O arquivo é TOML legível, morando no diretório de configuração do sistema
operacional (`QStandardPaths.AppConfigLocation`), conforme
`02-arquitetura.md` §8.1. A configuração **nunca** guarda segredo: credenciais
vivem no keyring do SO (ver `core/security.py` nas tarefas seguintes).

Dois princípios orientam este módulo:

* **Imutabilidade.** `AppConfig` é uma dataclass congelada; alterar uma
  configuração é produzir outra instância via `dataclasses.replace`. Isso
  impede que duas threads compartilhem um objeto parcialmente atualizado.
* **Falha nunca impede a abertura.** `load_config` devolve os padrões quando o
  arquivo não existe, está corrompido ou tem valor inválido — o cliente
  precisa iniciar para que o usuário possa consertar a configuração pela
  interface. Os valores ilegíveis caem no padrão um a um, e não como um bloco.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from PySide6.QtCore import QCoreApplication, QStandardPaths

APP_NAME = "PyMailClient"
ORG_NAME = "PyMail"

CONFIG_FILE_NAME = "config.toml"
DB_FILE_NAME = "pymail.db"
LOG_DIR_NAME = "logs"
ATTACHMENTS_DIR_NAME = "attachments"

#: Temas aceitos por `theme` (RF-UI-06): o sistema decide, ou o usuário força.
THEMES = ("system", "light", "dark")

#: Densidades aceitas por `list_density` (RF-UI-09).
DENSITIES = ("comfortable", "compact")

#: Limites de `undo_send_delay_s` em segundos (RF-SND-03).
UNDO_SEND_MIN_S = 5
UNDO_SEND_MAX_S = 30


def _setting_types() -> dict[str, type]:
    """Mapeia nome de campo para o tipo esperado no arquivo TOML.

    Existe porque `from __future__ import annotations` transforma `f.type` em
    texto: a checagem de tipo precisa de uma fonte explícita para continuar
    funcionando quando alguém trocar `int` por `str` no dataclass.
    """
    return {
        "undo_send_delay_s": int,
        "poll_interval_s": int,
        "body_cache_limit_bytes": int,
        "mark_read_delay_ms": int,
        "search_debounce_ms": int,
        "use_idle": bool,
        "theme": str,
        "list_density": str,
        "header_batch_size": int,
    }


_SETTINGS: dict[str, type] = _setting_types()


def _writable_location(location: QStandardPaths.StandardLocation) -> Path:
    """Resolve um `StandardLocation` do Qt, garantindo que a organização e a
    aplicação estejam nomeadas — sem isso o Qt devolve caminhos genéricos que
    não correspondem ao diretório de dados descrito na spec."""
    if QCoreApplication.applicationName() != APP_NAME:
        QCoreApplication.setApplicationName(APP_NAME)
    if QCoreApplication.organizationName() != ORG_NAME:
        QCoreApplication.setOrganizationName(ORG_NAME)
    return Path(QStandardPaths.writableLocation(location))


def default_data_dir() -> Path:
    """Diretório do banco e dos anexos (`QStandardPaths.AppDataLocation`)."""
    return _writable_location(QStandardPaths.StandardLocation.AppDataLocation)


def default_config_dir() -> Path:
    """Diretório do `config.toml` (`QStandardPaths.AppConfigLocation`)."""
    return _writable_location(QStandardPaths.StandardLocation.AppConfigLocation)


def default_log_dir() -> Path:
    return default_data_dir() / LOG_DIR_NAME


def default_attachments_dir() -> Path:
    return default_data_dir() / ATTACHMENTS_DIR_NAME


def default_config_path() -> Path:
    return default_config_dir() / CONFIG_FILE_NAME


def default_db_path() -> Path:
    return default_data_dir() / DB_FILE_NAME


@dataclass(frozen=True, slots=True)
class AppConfig:
    """Configuração do aplicativo, persistida como TOML.

    Os campos `*_dir` são resolvidos no momento da construção e **não** são
    serializados: eles são consequência do sistema operacional, não escolha do
    usuário, e gravar um caminho absoluto no arquivo quebraria a portabilidade
    do perfil entre máquinas.
    """

    # Janela do Undo Send em segundos (RF-SND-03, faixa 5..30).
    undo_send_delay_s: int = 10
    # Intervalo de verificação de novas mensagens quando não há IDLE (RF-MSG-05).
    poll_interval_s: int = 60
    # Teto do cache de corpos em bytes (RF-MSG-06).
    body_cache_limit_bytes: int = 500 * 1024 * 1024
    # Atraso antes de marcar como lida ao abrir uma mensagem (RF-RD-09).
    mark_read_delay_ms: int = 1500
    # Debounce da busca incremental (RF-SRCH-02).
    search_debounce_ms: int = 250
    # Usar IDLE quando o servidor suportar (RF-MSG-05, RF-SET-02).
    use_idle: bool = True
    # Tema: "system" | "light" | "dark" (RF-UI-06).
    theme: str = "system"
    # Densidade da lista: "comfortable" | "compact" (RF-UI-09).
    list_density: str = "comfortable"
    # Número máximo de lotes de cabeçalhos por sincronização inicial.
    header_batch_size: int = 200

    # Diretórios resolvidos pelo SO — derivados, nunca persistidos.
    data_dir: Path = field(default_factory=default_data_dir)
    config_dir: Path = field(default_factory=default_config_dir)
    log_dir: Path = field(default_factory=default_log_dir)
    attachments_dir: Path = field(default_factory=default_attachments_dir)

    def __post_init__(self) -> None:
        # Cada validação recusa o valor com ValueError: um arquivo de
        # configuração é entrada do usuário, e entrada inválida precisa de
        # diagnóstico, não de coerção silenciosa.
        if not UNDO_SEND_MIN_S <= self.undo_send_delay_s <= UNDO_SEND_MAX_S:
            raise ValueError(
                f"undo_send_delay_s must be between {UNDO_SEND_MIN_S} and "
                f"{UNDO_SEND_MAX_S} seconds, got {self.undo_send_delay_s}"
            )
        if self.poll_interval_s <= 0:
            raise ValueError(f"poll_interval_s must be positive, got {self.poll_interval_s}")
        if self.body_cache_limit_bytes <= 0:
            raise ValueError(
                f"body_cache_limit_bytes must be positive, got {self.body_cache_limit_bytes}"
            )
        if self.mark_read_delay_ms < 0:
            raise ValueError(
                f"mark_read_delay_ms must not be negative, got {self.mark_read_delay_ms}"
            )
        if self.search_debounce_ms < 0:
            raise ValueError(
                f"search_debounce_ms must not be negative, got {self.search_debounce_ms}"
            )
        if self.theme not in THEMES:
            raise ValueError(f"theme must be one of {THEMES}, got {self.theme!r}")
        if self.list_density not in DENSITIES:
            raise ValueError(f"list_density must be one of {DENSITIES}, got {self.list_density!r}")
        if self.header_batch_size <= 0:
            raise ValueError(f"header_batch_size must be positive, got {self.header_batch_size}")

    @property
    def config_path(self) -> Path:
        return self.config_dir / CONFIG_FILE_NAME

    @property
    def db_path(self) -> Path:
        return self.data_dir / DB_FILE_NAME

    def with_overrides(self, **overrides: Any) -> AppConfig:
        """Cria uma cópia com campos trocados, revalidando o resultado."""
        return replace(self, **overrides)

    def to_toml(self) -> str:
        """Serializa apenas as preferências do usuário, em ordem estável.

        A ordem estável não é estética: um arquivo de configuração deve ter
        diff legível, e um TOML serializado em ordem deitória de `dataclasses`
        tornaria cada alteração uma rewritagem completa do arquivo.
        """
        lines = [
            "# PyMail Client — configuração local.",
            "# Não contém credenciais: elas ficam no cofre do sistema operacional.",
        ]
        for name in _SETTINGS:
            lines.append(f"{name} = {_toml_value(getattr(self, name))}")
        return "\n".join(lines) + "\n"

    @classmethod
    def from_toml(cls, text: str) -> AppConfig:
        """Constrói a configuração a partir do texto TOML.

        Chaves desconhecidas são ignoradas (uma versão futura do aplicativo não
        pode impedir uma versão antiga de abrir o perfil) e valores inválidos
        caem no padrão correspondente, um a um, para que uma única linha ruim
        não descarte as demais preferências.
        """
        try:
            raw = tomllib.loads(text)
        except tomllib.TOMLDecodeError:
            return cls()

        defaults = cls()
        values: dict[str, Any] = {}
        for name, expected in _SETTINGS.items():
            if name not in raw:
                continue
            candidate = raw[name]
            if not isinstance(candidate, expected) or isinstance(candidate, bool) is not (
                expected is bool
            ):
                continue
            try:
                # Valida por tentativa: um único valor fora de faixa não pode
                # invalidar as preferências vizinhas.
                values[name] = candidate
                replace(defaults, **values)
            except ValueError:
                del values[name]
        return replace(defaults, **values)


def _toml_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    return str(value)


def save_config(config: AppConfig, path: Path | None = None) -> Path:
    """Grava a configuração em `path` (padrão: `AppConfigLocation/config.toml`).

    A gravação é atômica: escreve num arquivo temporário no mesmo diretório e
    substitui o destino, para que uma queda de energia no meio não deixe um
    `config.toml` truncado — o usuário perderia todas as preferências.
    """
    target = Path(path) if path is not None else config.config_path
    target.parent.mkdir(parents=True, exist_ok=True)

    tmp = target.with_name(target.name + ".tmp")
    tmp.write_text(config.to_toml(), encoding="utf-8")
    os.replace(tmp, target)
    _restrict_permissions(target)
    return target


def _restrict_permissions(path: Path) -> None:
    """Aplica 0600 no arquivo de configuração (02-arquitetura.md §8.1).

    O arquivo guarda hosts de servidor, nomes de usuário e a lista de
    remetentes com imagens autorizadas — metadados de comunicação, não
    segredos, mas ainda privados. Em Windows não há modo POSIX; ali a proteção
    é a ACL do perfil do usuário e o erro é esperado e ignorado.
    """
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def load_config(path: Path | None = None) -> AppConfig:
    """Lê a configuração, devolvendo os padrões quando ela não está disponível.

    Não levanta exceção em nenhum caso: arquivo ausente, ilegível, com TOML
    inválido ou com conteúdo inesperado resultam em `AppConfig()`.
    """
    target = Path(path) if path is not None else default_config_path()
    try:
        text = target.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return AppConfig()
    try:
        return AppConfig.from_toml(text)
    except Exception:  # noqa: BLE001 — última linha de defesa, ver docstring
        # Fail-safe: uma configuração corrompida não pode impedir a abertura
        # do cliente; o padrão é sempre um estado inicializável.
        return AppConfig()
