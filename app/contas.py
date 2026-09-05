"""
Contas de usuário, sessão e registro de atividade do xmljats.

Armazenamento: XMLJATS_DATA/usuarios.json (lista de {id, email, nome, papel, senha, criado_em, atividade}); a senha
guarda só o hash PBKDF2-HMAC-SHA256 com sal. Sessão: cookie "xmljats_sessao" assinado com HMAC-SHA256 (segredo em
APP_SEGREDO ou, na falta, gerado uma vez em XMLJATS_DATA/segredo.txt).

Papéis: "admin" (administra usuários, revistas e vê o sistema inteiro), "operador" (vê todos os documentos) e
"cliente" (vê apenas os próprios documentos).

Atividade: cada requisição autenticada atualiza `atividade` com o último acesso, o IP e o navegador. É o que alimenta
"online agora" e "última vez visto" no painel administrativo. Todos os horários usam o fuso de Brasília (app/tempo.py).

Bootstrap: sem usuários cadastrados e com APP_SENHA definida, o primeiro acesso cria o admin "admin" com essa senha.
Sem usuários e sem APP_SENHA (desenvolvimento local), o app roda sem login como "local".
"""
import base64
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

from tempo import agora, agora_iso, le  # noqa: E402  (app/tempo.py)

RE_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$|^[a-z0-9_.-]{3,32}$")  # e-mail ou login simples (ex.: admin)
PAPEIS = ("admin", "operador", "cliente")
ROTULO_PAPEL = {"admin": "administrador", "operador": "operador", "cliente": "cliente"}
COOKIE = "xmljats_sessao"
DURACAO_SESSAO = 12 * 3600  # 12 horas
INTERVALO_ATIVIDADE = 60  # só regrava a atividade se passou mais de 1 min (evita escrever a cada clique)


class Contas:
    def __init__(self, pasta_dados: Path):
        self.pasta = Path(pasta_dados)
        self.arquivo = self.pasta / "usuarios.json"

    # ------------------------------------------------------------ armazenamento
    def _carrega(self) -> List[dict]:
        if not self.arquivo.exists():
            return []
        try:
            with io.open(self.arquivo, encoding="utf-8") as f:
                return json.load(f).get("usuarios", [])
        except (OSError, ValueError):
            return []

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

    def por_email(self, email: str) -> Optional[dict]:
        email = (email or "").strip().lower()
        return next((self._publico(u) for u in self._carrega() if u["email"] == email), None)

    # ------------------------------------------------------------ senhas
    @staticmethod
    def hash_senha(senha: str, sal: Optional[bytes] = None) -> str:
        sal = sal or secrets.token_bytes(16)
        h = hashlib.pbkdf2_hmac("sha256", senha.encode("utf-8"), sal, 200_000)
        return "pbkdf2$" + sal.hex() + "$" + h.hex()

    @staticmethod
    def verifica_senha(senha: str, guardada: str) -> bool:
        try:
            _, sal_hex, h_hex = (guardada or "").split("$")
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
             "criado_em": agora_iso(), "atividade": {}, "email_confirmado": False, "avatar": None}
        usuarios.append(u)
        self._grava(usuarios)
        return self._publico(u)

    def _altera(self, uid: str, muda):
        usuarios = self._carrega()
        for u in usuarios:
            if u["id"] == uid:
                muda(u, usuarios)
                self._grava(usuarios)
                return self._publico(u)
        raise ValueError("Usuário não encontrado.")

    def define_senha(self, uid: str, senha: str):
        erro = self.valida_senha(senha)
        if erro:
            raise ValueError(erro)
        return self._altera(uid, lambda u, _: u.update(senha=self.hash_senha(senha)))

    def define_papel(self, uid: str, papel: str):
        if papel not in PAPEIS:
            raise ValueError("Papel inválido.")

        def muda(u, usuarios):
            if u["papel"] == "admin" and papel != "admin" and sum(1 for x in usuarios if x["papel"] == "admin") == 1:
                raise ValueError("Este é o último administrador; promova outro antes de rebaixar este.")
            u["papel"] = papel

        return self._altera(uid, muda)

    def define_dados(self, uid: str, nome: Optional[str] = None, email: Optional[str] = None):
        """Muda nome e/ou e-mail (usado pelo administrador e pela própria pessoa)."""
        nome = (nome or "").strip()
        email = (email or "").strip().lower()

        def muda(u, usuarios):
            if nome:
                u["nome"] = nome
            if email and email != u["email"]:
                if not RE_EMAIL.match(email):
                    raise ValueError("Informe um e-mail válido.")
                if any(x["email"] == email and x["id"] != uid for x in usuarios):
                    raise ValueError(f"Já existe usuário com o e-mail {email}.")
                u["email"] = email
                u["email_confirmado"] = False  # endereço novo precisa ser confirmado de novo

        if not nome and not email:
            raise ValueError("Nada para alterar.")
        return self._altera(uid, muda)

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

    # ------------------------------------------------------------ confirmacao de e-mail e foto
    def define_token_confirmacao(self, uid: str, token: str):
        return self._altera(uid, lambda u, _: u.update(token_confirmacao=token, token_em=agora_iso()))

    def confirma_por_token(self, token: str) -> Optional[dict]:
        """Marca o e-mail como confirmado e queima o token. Devolve o usuário ou None."""
        if not token:
            return None
        usuarios = self._carrega()
        for u in usuarios:
            if u.get("token_confirmacao") and hmac.compare_digest(u["token_confirmacao"], token):
                u["email_confirmado"] = True
                u["confirmado_em"] = agora_iso()
                u.pop("token_confirmacao", None)
                self._grava(usuarios)
                return self._publico(u)
        return None

    def define_confirmado(self, uid: str, confirmado: bool = True):
        return self._altera(uid, lambda u, _: u.update(email_confirmado=bool(confirmado)))

    def define_avatar(self, uid: str, arquivo: Optional[str]):
        return self._altera(uid, lambda u, _: u.update(avatar=arquivo))

    # ------------------------------------------------------------ atividade
    def registra_acesso(self, uid: str, ip: Optional[str], navegador: Optional[str], rota: Optional[str] = None):
        """Marca o último acesso do usuário. Só grava se passou INTERVALO_ATIVIDADE desde a última vez."""
        usuarios = self._carrega()
        for u in usuarios:
            if u["id"] != uid:
                continue
            at = u.setdefault("atividade", {})
            ultimo = le(at.get("ultimo_acesso"))
            if ultimo and (agora() - ultimo).total_seconds() < INTERVALO_ATIVIDADE and at.get("ip") == ip:
                return
            at["ultimo_acesso"] = agora_iso()
            at["ip"] = ip
            at["navegador"] = (navegador or "")[:200]
            if rota:
                at["ultima_rota"] = rota[:120]
            at["acessos"] = int(at.get("acessos") or 0) + 1
            self._grava(usuarios)
            return

    def registra_login(self, uid: str, ip: Optional[str], navegador: Optional[str]):
        def muda(u, _):
            at = u.setdefault("atividade", {})
            at["ultimo_login"] = agora_iso()
            at["ultimo_acesso"] = agora_iso()
            at["ip"] = ip
            at["navegador"] = (navegador or "")[:200]
            at["logins"] = int(at.get("logins") or 0) + 1
            at["acessos"] = int(at.get("acessos") or 0) + 1

        try:
            self._altera(uid, muda)
        except ValueError:
            pass

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
