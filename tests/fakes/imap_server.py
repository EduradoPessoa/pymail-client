"""Servidor IMAP falso para testes (T-04, T-10, T-11, T-12, T-14, T-17).

Implementa um subconjunto do protocolo IMAP4rev1 sobre `ThreadingTCPServer`.
Registra todos os comandos recebidos em `server.commands` como tuplas
`(tag, verb, args)`, o que torna verificáveis as tarefas futuras.
"""

from __future__ import annotations

import ssl
import threading
import time
from dataclasses import dataclass
from socketserver import BaseRequestHandler, ThreadingTCPServer


@dataclass
class ImapCommand:
    """Comando IMAP parseado."""

    tag: str
    verb: str
    args: list[str]


class ImapServer(ThreadingTCPServer):
    """Servidor IMAP falso com registro de comandos."""

    allow_reuse_address = True
    daemon_threads = True

    def __init__(
        self,
        server_address: tuple[str, int],
        *,
        use_tls: bool = True,
        certfile: str | None = None,
        keyfile: str | None = None,
        refuse_login: bool = False,
        capabilities: list[str] | None = None,
    ):
        super().__init__(server_address, _ImapRequestHandler)
        self.use_tls = use_tls
        self.certfile = certfile
        self.keyfile = keyfile
        self.refuse_login = refuse_login
        self.capabilities = capabilities or [
            "IMAP4rev1",
            "STARTTLS",
            "AUTH=PLAIN",
            "LOGIN-REFERRALS",
            "ID",
            "ENABLE",
            "MOVE",
            "IDLE",
            "NAMESPACE",
        ]
        self.commands: list[ImapCommand] = []
        self._folders = {
            "INBOX": {
                "delimiter": "/",
                "flags": ["\\HasNoChildren"],
                "messages": [],
                "uidvalidity": 1,
                "uidnext": 1,
            }
        }
        self._selected_folder: str | None = None
        self._authenticated = False
        self._tag_counter = 0
        self._shutdown = False

    @property
    def port(self) -> int:
        return self.server_address[1]

    def record_command(self, tag: str, verb: str, args: list[str]) -> None:
        self.commands.append(ImapCommand(tag=tag, verb=verb.upper(), args=args))

    def add_message(self, folder: str, raw: bytes) -> int:
        """Adiciona uma mensagem à pasta, retorna o UID."""
        if folder not in self._folders:
            self._folders[folder] = {
                "delimiter": "/",
                "flags": ["\\HasNoChildren"],
                "messages": [],
                "uidvalidity": 1,
                "uidnext": 1,
            }
        folder_data = self._folders[folder]
        uid = folder_data["uidnext"]
        folder_data["messages"].append({"uid": uid, "raw": raw, "flags": []})
        folder_data["uidnext"] += 1
        return uid

    def set_uidvalidity(self, folder: str, uidvalidity: int) -> None:
        if folder in self._folders:
            self._folders[folder]["uidvalidity"] = uidvalidity

    def shutdown_server(self) -> None:
        self._shutdown = True
        self.shutdown()


class _ImapRequestHandler(BaseRequestHandler):
    """Handler para uma conexão IMAP."""

    def setup(self) -> None:
        self.server: ImapServer
        self._buffer = b""
        self._tls_started = False
        self._authenticated = False
        self._selected_folder: str | None = None

        # Para IMAPS (use_tls=True), fazer handshake TLS imediatamente antes de qualquer dado
        if self.server.use_tls and self.server.certfile and self.server.keyfile:
            self._start_tls()

        self._send_welcome()

    def _send_welcome(self) -> None:
        self._send(
            b"* OK [CAPABILITY "
            + b" ".join(c.encode() for c in self.server.capabilities)
            + b"] Fake IMAP server ready\r\n"
        )

    def handle(self) -> None:
        try:
            while not self.server._shutdown:
                line = self._read_line()
                if not line:
                    break
                self._process_command(line)
        except (ConnectionError, ssl.SSLError, OSError):
            pass
        finally:
            try:
                self.request.close()
            except OSError:
                pass

    def _start_tls(self) -> None:
        if self.server.certfile and self.server.keyfile:
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.load_cert_chain(self.server.certfile, self.server.keyfile)
            self.request = context.wrap_socket(self.request, server_side=True)
            self._tls_started = True

    def _read_line(self) -> str | None:
        while b"\r\n" not in self._buffer:
            chunk = self.request.recv(4096)
            if not chunk:
                return None
            self._buffer += chunk
        line, self._buffer = self._buffer.split(b"\r\n", 1)
        return line.decode("utf-8", errors="replace")

    def _send(self, data: bytes) -> None:
        try:
            self.request.sendall(data)
        except OSError:
            pass

    def _send_line(self, line: str) -> None:
        self._send((line + "\r\n").encode("utf-8"))

    def _process_command(self, line: str) -> None:
        line = line.strip()
        if not line:
            return

        parts = line.split()
        if len(parts) < 2:
            self._send_line("* BAD Invalid command")
            return

        tag = parts[0]
        verb = parts[1].upper()
        args = parts[2:]

        self.server.record_command(tag, verb, args)

        handler = getattr(self, f"_cmd_{verb}", None)
        if handler:
            handler(tag, args)
        else:
            self._send_line(f"{tag} BAD Unknown command {verb}")

    def _cmd_CAPABILITY(self, tag: str, args: list[str]) -> None:
        self._send_line(f"* CAPABILITY {' '.join(self.server.capabilities)}")
        self._send_line(f"{tag} OK CAPABILITY completed")

    def _cmd_STARTTLS(self, tag: str, args: list[str]) -> None:
        if not self.server.use_tls:
            self._send_line(f"{tag} NO STARTTLS not available")
            return
        self._send_line(f"{tag} OK Begin TLS negotiation now")
        self._start_tls()

    def _cmd_LOGIN(self, tag: str, args: list[str]) -> None:
        if len(args) < 2:
            self._send_line(f"{tag} BAD LOGIN requires username and password")
            return
        if self.server.refuse_login:
            self._send_line(f"{tag} NO LOGIN failed")
            return
        self._authenticated = True
        self._send_line(f"{tag} OK LOGIN completed")

    def _cmd_LOGOUT(self, tag: str, args: list[str]) -> None:
        self._send_line("* BYE Fake IMAP server logging out")
        self._send_line(f"{tag} OK LOGOUT completed")

    def _cmd_NOOP(self, tag: str, args: list[str]) -> None:
        self._send_line(f"{tag} OK NOOP completed")

    def _cmd_LIST(self, tag: str, args: list[str]) -> None:
        if not self._authenticated:
            self._send_line(f"{tag} NO Not authenticated")
            return
        for name, data in self.server._folders.items():
            flags = " ".join(data["flags"])
            self._send_line(f'* LIST ({flags}) "{data["delimiter"]}" {name}')
        self._send_line(f"{tag} OK LIST completed")

    def _cmd_SELECT(self, tag: str, args: list[str]) -> None:
        if not self._authenticated:
            self._send_line(f"{tag} NO Not authenticated")
            return
        if not args:
            self._send_line(f"{tag} BAD SELECT requires folder name")
            return
        folder = args[0].strip('"')
        if folder not in self.server._folders:
            self._send_line(f"{tag} NO Folder not found")
            return
        self._selected_folder = folder
        folder_data = self.server._folders[folder]
        self._send_line(f"* {len(folder_data['messages'])} EXISTS")
        self._send_line("* 0 RECENT")
        self._send_line(f"* OK [UIDVALIDITY {folder_data['uidvalidity']}] UID validity")
        self._send_line(f"* OK [UIDNEXT {folder_data['uidnext']}] Predicted next UID")
        self._send_line(f"{tag} OK [READ-WRITE] SELECT completed")

    def _cmd_UID(self, tag: str, args: list[str]) -> None:
        if not self._authenticated:
            self._send_line(f"{tag} NO Not authenticated")
            return
        if not args:
            self._send_line(f"{tag} BAD UID requires subcommand")
            return
        subcmd = args[0].upper()
        sub_args = args[1:]
        handler = getattr(self, f"_cmd_UID_{subcmd}", None)
        if handler:
            handler(tag, sub_args)
        else:
            self._send_line(f"{tag} BAD Unknown UID subcommand {subcmd}")

    def _cmd_UID_FETCH(self, tag: str, args: list[str]) -> None:
        if not self._selected_folder:
            self._send_line(f"{tag} NO No folder selected")
            return
        # Parse: UID FETCH <sequence> <what>
        if len(args) < 2:
            self._send_line(f"{tag} BAD FETCH requires sequence and data items")
            return
        sequence = args[0]
        what = " ".join(args[1:])

        folder_data = self.server._folders[self._selected_folder]
        messages = folder_data["messages"]

        for msg in messages:
            uid = msg["uid"]
            if self._match_sequence(uid, sequence):
                self._send_fetch_response(uid, msg, what)
        self._send_line(f"{tag} OK FETCH completed")

    def _cmd_UID_STORE(self, tag: str, args: list[str]) -> None:
        if not self._selected_folder:
            self._send_line(f"{tag} NO No folder selected")
            return
        if len(args) < 3:
            self._send_line(f"{tag} BAD STORE requires sequence, action, and flags")
            return
        sequence = args[0]
        action = args[1].upper()
        flags = args[2:]

        folder_data = self.server._folders[self._selected_folder]
        for msg in folder_data["messages"]:
            uid = msg["uid"]
            if self._match_sequence(uid, sequence):
                if action in ("+FLAGS", "+FLAGS.SILENT"):
                    for f in flags:
                        f = f.strip("()")
                        if f not in msg["flags"]:
                            msg["flags"].append(f)
                elif action in ("-FLAGS", "-FLAGS.SILENT"):
                    for f in flags:
                        f = f.strip("()")
                        if f in msg["flags"]:
                            msg["flags"].remove(f)
                elif action in ("FLAGS", "FLAGS.SILENT"):
                    msg["flags"] = [f.strip("()") for f in flags]
                self._send_line(f"* {uid} FETCH (FLAGS ({' '.join(msg['flags'])}) UID {uid})")
        self._send_line(f"{tag} OK STORE completed")

    def _cmd_UID_SEARCH(self, tag: str, args: list[str]) -> None:
        if not self._selected_folder:
            self._send_line(f"{tag} NO No folder selected")
            return
        folder_data = self.server._folders[self._selected_folder]
        uids = [str(msg["uid"]) for msg in folder_data["messages"]]
        self._send_line(f"* SEARCH {' '.join(uids) if uids else ''}")
        self._send_line(f"{tag} OK SEARCH completed")

    def _cmd_UID_MOVE(self, tag: str, args: list[str]) -> None:
        if "MOVE" not in self.server.capabilities:
            self._send_line(f"{tag} NO MOVE not supported")
            return
        if len(args) < 2:
            self._send_line(f"{tag} BAD MOVE requires sequence and destination")
            return
        # Simplified: just report success
        self._send_line(f"{tag} OK MOVE completed")

    def _cmd_IDLE(self, tag: str, args: list[str]) -> None:
        if "IDLE" not in self.server.capabilities:
            self._send_line(f"{tag} NO IDLE not supported")
            return
        self._send_line("+ idling")
        # Wait for DONE
        line = self._read_line()
        if line and line.strip().upper() == "DONE":
            self._send_line(f"{tag} OK IDLE terminated")

    def _match_sequence(self, uid: int, sequence: str) -> bool:
        if sequence == "*":
            return True
        if ":" in sequence:
            start, end = sequence.split(":", 1)
            start = int(start) if start != "*" else 1
            end = int(end) if end != "*" else float("inf")
            return start <= uid <= end
        return uid == int(sequence)

    def _send_fetch_response(self, uid: int, msg: dict, what: str) -> None:
        what = what.strip("()")
        parts = []
        if "FLAGS" in what.upper():
            parts.append(f"FLAGS ({' '.join(msg['flags'])})")
        if "UID" in what.upper():
            parts.append(f"UID {uid}")
        if "RFC822.SIZE" in what.upper():
            parts.append(f"RFC822.SIZE {len(msg['raw'])}")
        if "ENVELOPE" in what.upper():
            parts.append(self._build_envelope(msg["raw"]))
        if "BODYSTRUCTURE" in what.upper():
            parts.append(self._build_bodystructure(msg["raw"]))
        if "BODY.PEEK[]" in what.upper() or "BODY[]" in what.upper():
            parts.append(f"BODY[] {{{len(msg['raw'])}}}")
            self._send_line(f"* {uid} FETCH ({' '.join(parts)})")
            self._send(msg["raw"] + b"\r\n")
            return
        if parts:
            self._send_line(f"* {uid} FETCH ({' '.join(parts)})")

    def _build_envelope(self, raw: bytes) -> str:
        # Simplified envelope
        return (
            'ENVELOPE ("Mon, 1 Jan 2024 00:00:00 +0000" "Test" '
            '(("Test" NIL "test" "example.com")) '
            '(("Test" NIL "test" "example.com")) NIL NIL '
            '(("Test" NIL "test" "example.com")) NIL "<msg@example.com>")'
        )

    def _build_bodystructure(self, raw: bytes) -> str:
        return (
            'BODYSTRUCTURE ("TEXT" "PLAIN" ("CHARSET" "UTF-8") '
            'NIL NIL "7BIT" 100 1 NIL NIL NIL NIL)'
        )


def make_self_signed_cert() -> tuple[str, str]:
    """Gera um certificado auto-assinado temporário para testes TLS."""
    import datetime
    import tempfile

    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = issuer = x509.Name([x509.NameAttribute(x509.NameOID.COMMON_NAME, "test")])
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.datetime.now(datetime.UTC))
        .not_valid_after(datetime.datetime.now(datetime.UTC) + datetime.timedelta(days=1))
        .add_extension(x509.SubjectAlternativeName([x509.DNSName("localhost")]), critical=False)
        .sign(key, hashes.SHA256())
    )

    cert_pem = cert.public_bytes(serialization.Encoding.PEM)
    key_pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )

    cert_file = tempfile.NamedTemporaryFile(mode="wb", delete=False, suffix=".pem")
    cert_file.write(cert_pem)
    cert_file.close()

    key_file = tempfile.NamedTemporaryFile(mode="wb", delete=False, suffix=".pem")
    key_file.write(key_pem)
    key_file.close()

    return cert_file.name, key_file.name


def imap_server_factory(
    *,
    refuse_login: bool = False,
    use_tls: bool = True,
    capabilities: list[str] | None = None,
) -> ImapServer:
    """Factory para criar servidores IMAP de teste."""
    certfile = keyfile = None
    if use_tls:
        certfile, keyfile = make_self_signed_cert()
    server = ImapServer(
        ("127.0.0.1", 0),
        use_tls=use_tls,
        certfile=certfile,
        keyfile=keyfile,
        refuse_login=refuse_login,
        capabilities=capabilities,
    )
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    # Wait for server to be ready
    time.sleep(0.1)
    return server


def tls_server_selfsigned() -> ImapServer:
    """Servidor TLS com certificado auto-assinado."""
    certfile, keyfile = make_self_signed_cert()
    server = ImapServer(
        ("127.0.0.1", 0),
        use_tls=True,
        certfile=certfile,
        keyfile=keyfile,
        refuse_login=False,
    )
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    time.sleep(0.1)
    return server


def plain_server() -> ImapServer:
    """Servidor sem TLS (texto claro)."""
    server = ImapServer(("127.0.0.1", 0), use_tls=False)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    time.sleep(0.1)
    return server
