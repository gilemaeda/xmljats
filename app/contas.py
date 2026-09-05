"""
Contas de usuário e sessão do xmljats.

Armazenamento: XMLJATS_DATA/usuarios.json (lista de {id, email, nome, papel, senha, criado_em}); a senha guarda só o
hash PBKDF2-HMAC-SHA256 com sal. Sessão: cookie "xmljats_sessao" assinado com HMAC-SHA256 (segredo em APP_SEGREDO ou,
na falta, gerado uma vez em XMLJATS_DATA/segredo.txt). Papéis: "admin" (gerencia usuários e revistas), "operador" (vê todos os documentos) e "cliente" (vê só os seus).

Bootstrap: sem usuários cadastrados e com APP_SENHA definida, o primeiro acesso cria o admin "admin" com essa senha.
Sem usuários e sem APP_SENHA (desenvolvimento local), o app roda sem login como "local".
"""
import base64
import datetime as dt
import hashlib
import hmac
import io
import json
import os
import re
import secrets
import time
from pathlib import Path
from typing import List, Optional

RE_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$|^[a-z0-9_.-]{3,32}$")  # e-mail ou login simples (ex.: admin)
PAPEIS = ("admin", "operador", "cliente")
COOKIE = "xmljats_sessao"
DURACAO_SESSAO = 12 * 3600  # 12 horas


class Contas:
    def __init__(self, pasta_dados: Path):
        self.pasta = Path(pasta_dados)
        self.arquivo = self.pasta / "usuarios.json"

    # ------------------------------------------------------------ armazenamento
    def _carrega(self) -> List[dict]:
        if not self.arquivo.exists():
            return []
        with io.open(self.arquivo, encoding="utf-8") as f:
            return json.load(f).get("usuarios", [])

    def _grava(self, usuarios: List[dict]):
        self.pasta.mkdir(parents=True, exist_ok=True)
        tmp = self.arquivo.with_suffix(".tmp")
        with io.open(tmp, "w", encoding="utf-8") as f:
            json.dump({"usuarios": usuarios}, f, ensure_ascii=False, indent=2)
        os.replace(tmp, self.arquivo)

    def lista(self) -> List[dict]:
        return [self._publico(u) for u in self._carrega()]

    @staticmethod
    def _publico(u: dict) -> dict:
        return {k: v for k, v in u.items() if k != "senha"}

    def por_id(self, uid: str) -> Optional[dict]:
        return next((self._publico(u) for u in self._carrega() if u["id"] == uid), None)

    # ------------------------------------------------------------ senhas
    @staticmethod
    def hash_senha(senha: str, sal: Optional[bytes] = None) -> str:
        sal = sal or secrets.token_bytes(16)
        h = hashlib.pbkdf2_hmac("sha256", senha.encode("utf-8"), sal, 200_000)
        return "pbkdf2$" + sal.hex() + "$" + h.hex()

    @staticmethod
    def verifica_senha(senha: str, guardada: str) -> bool:
        try:
            _, sal_hex, h_hex = guardada.split("$")
        except ValueError:
            return False
        h = hashlib.pbkdf2_hmac("sha256", senha.encode("utf-8"), bytes.fromhex(sal_hex), 200_000)
        return hmac.compare_digest(h.hex(), h_hex)

    @staticmethod
    def valida_senha(senha: str) -> Optional[str]:
        if len(senha or "") < 8:
            return "A senha precisa ter pelo menos 8 caracteres."
        return None

    # ------------------------------------------------------------ CRUD
    def cria(self, email: str, nome: str, senha: str, papel: str = "operador") -> dict:
        email = (email or "").strip().lower()
        nome = (nome or "").strip()
        if not RE_EMAIL.match(email):
            raise ValueError("Informe um e-mail válido (ou um login simples, como 'admin').")
        if not nome:
            raise ValueError("Informe o nome.")
        if papel not in PAPEIS:
            raise ValueError("Papel inválido.")
        erro = self.valida_senha(senha)
        if erro:
            raise ValueError(erro)
        usuarios = self._carrega()
        if any(u["email"] == email for u in usuarios):
            raise ValueError(f"Já existe usuário com o e-mail {email}.")
        u = {"id": secrets.token_hex(6), "email": email, "nome": nome, "papel": papel, "senha": self.hash_senha(senha),
             "criado_em": dt.datetime.now().isoformat(timespec="seconds")}
        usuarios.append(u)
        self._grava(usuarios)
        return self._publico(u)

    def define_senha(self, uid: str, senha: str):
        erro = self.valida_senha(senha)
        if erro:
            raise ValueError(erro)
        usuarios = self._carrega()
        for u in usuarios:
            if u["id"] == uid:
                u["senha"] = self.hash_senha(senha)
                self._grava(usuarios)
                return
        raise ValueError("Usuário não encontrado.")

    def define_papel(self, uid: str, papel: str):
        if papel not in PAPEIS:
            raise ValueError("Papel inválido.")
        usuarios = self._carrega()
        for u in usuarios:
            if u["id"] == uid:
                u["papel"] = papel
                self._grava(usuarios)
                return
        raise ValueError("Usuário não encontrado.")

    def remove(self, uid: str):
        usuarios = self._carrega()
        restantes = [u for u in usuarios if u["id"] != uid]
        if len(restantes) == len(usuarios):
            raise ValueError("Usuário não encontrado.")
        if not any(u["papel"] == "admin" for u in restantes):
            raise ValueError("Não dá para remover o último administrador.")
        self._grava(restantes)

    def autentica(self, email: str, senha: str) -> Optional[dict]:
        email = (email or "").strip().lower()
        for u in self._carrega():
            if u["email"] == email and self.verifica_senha(senha or "", u["senha"]):
                return self._publico(u)
        return None

    def garante_admin(self, senha_inicial: Optional[str]) -> Optional[dict]:
        """Primeiro acesso: sem usuários e com APP_SENHA, cria o admin 'admin'."""
        if self._carrega() or not senha_inicial:
            return None
        return self.cria("admin", "Administrador", senha_inicial, "admin")

    # ------------------------------------------------------------ sessão (cookie assinado)
    def _segredo(self) -> bytes:
        env = os.environ.get("APP_SEGREDO")
        if env:
            return env.encode("utf-8")
        arq = self.pasta / "segredo.txt"
        if not arq.exists():
            self.pasta.mkdir(parents=True, exist_ok=True)
            arq.write_text(secrets.token_hex(32), encoding="utf-8")
        return arq.read_text(encoding="utf-8").strip().encode("utf-8")

    def assina_sessao(self, uid: str, duracao: int = DURACAO_SESSAO) -> str:
        exp = int(time.time()) + duracao
        corpo = f"{uid}|{exp}".encode("utf-8")
        mac = hmac.new(self._segredo(), corpo, hashlib.sha256).digest()
        return base64.urlsafe_b64encode(corpo + b"|" + mac).decode("ascii")

    def le_sessao(self, token: Optional[str]) -> Optional[dict]:
        if not token:
            return None
        try:
            bruto = base64.urlsafe_b64decode(token.encode("ascii"))
            uid, exp, mac = bruto.split(b"|", 2)
        except Exception:  # noqa: BLE001
            return None
        esperado = hmac.new(self._segredo(), uid + b"|" + exp, hashlib.sha256).digest()
        if not hmac.compare_digest(mac, esperado) or int(exp) < time.time():
            return None
        return self.por_id(uid.decode("utf-8"))
