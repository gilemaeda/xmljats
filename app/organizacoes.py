"""Organizações: uma editora ou instituição (ou, no futuro, um parceiro revendedor) que é dona de revistas e agrupa pessoas.

Desde a etapa 2 do multi-tenant (multitenancy_proposta_v1.md), a organização guarda:
- `admins`: quem administra a organização (pessoas, papéis, revistas, uso). Não precisa ter papel em revista.
- `membros`: quem entrou pelo código de convite (ou foi vinculado pelo administrador). Membro ganha o papel de
  secretaria editorial em todas as revistas da organização (app/acesso.py cuida disso), inclusive nas criadas depois.
- `tipo`: "instituicao" ou "parceiro_revenda"; `pai`: organização parceira acima desta (futuro); `plano`: forma de cobrança.
Quem pode o quê nunca é um campo na conta: fica em papeis.json (papel por revista) e aqui (admins/membros).

Ninguém entra digitando o nome, só pelo código de convite (ou pelo administrador, em Usuários).
Armazenamento: XMLJATS_DATA/organizacoes.json — {"organizacoes": [{id, nome, tipo, plano, convite, admins, membros, pai,
criado_em, criado_por}]}. Registros de antes ganham os campos novos ao serem lidos.
"""
import json
import os
import re
import secrets
import tempfile
from pathlib import Path
from typing import List, Optional

from tempo import agora_iso

RE_NOME = re.compile(r"^\S.{1,78}\S$")
TIPOS = ("instituicao", "parceiro_revenda")
ROTULO_TIPO = {"instituicao": "instituição", "parceiro_revenda": "parceiro revendedor"}


def normaliza_convite(codigo: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", (codigo or "").upper())


def _completa(o: dict) -> dict:
    """Registro de antes da etapa 2 ganha os campos novos (sem mexer no arquivo até a próxima gravação)."""
    o.setdefault("tipo", "instituicao")
    o.setdefault("plano", None)
    o.setdefault("pai", None)
    o["admins"] = list(o.get("admins") or [])
    o["membros"] = list(o.get("membros") or [])
    return o


class Organizacoes:
    def __init__(self, arquivo: Path):
        self.arquivo = Path(arquivo)

    # ------------------------------------------------------------ arquivo
    def _carrega(self) -> list:
        if not self.arquivo.exists():
            return []
        try:
            with open(self.arquivo, encoding="utf-8") as f:
                dados = json.load(f)
        except (OSError, ValueError):
            return []
        lista = dados.get("organizacoes", []) if isinstance(dados, dict) else (dados or [])
        return [_completa(o) for o in lista]

    def _grava(self, lista: list) -> None:
        self.arquivo.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix="organizacoes-", suffix=".json", dir=str(self.arquivo.parent))
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump({"organizacoes": lista}, f, ensure_ascii=False, indent=1)
        os.replace(tmp, self.arquivo)

    # ------------------------------------------------------------ consulta
    def lista(self) -> List[dict]:
        return sorted(self._carrega(), key=lambda o: (o.get("nome") or "").lower())

    def por_id(self, oid: Optional[str]) -> Optional[dict]:
        if not oid:
            return None
        return next((o for o in self._carrega() if o["id"] == oid), None)

    def por_convite(self, codigo: str) -> Optional[dict]:
        codigo = normaliza_convite(codigo)
        if not codigo:
            return None
        return next((o for o in self._carrega() if o.get("convite") == codigo), None)

    def nome_de(self, oid: Optional[str]) -> str:
        o = self.por_id(oid)
        return o["nome"] if o else ""

    def pessoas(self, oid: Optional[str]) -> List[str]:
        """Ids de todo mundo ligado à organização: membros e administradores, sem repetir."""
        o = self.por_id(oid)
        if not o:
            return []
        vistos: List[str] = []
        for uid in o["membros"] + o["admins"]:
            if uid not in vistos:
                vistos.append(uid)
        return vistos

    # ------------------------------------------------------------ mudanças
    @staticmethod
    def valida_nome(nome: str, existentes: list, ignorar: Optional[str] = None) -> str:
        nome = " ".join((nome or "").split())
        if not RE_NOME.match(nome):
            raise ValueError("Nome da organização: de 3 a 80 caracteres.")
        if any(o["nome"].lower() == nome.lower() and o["id"] != ignorar for o in existentes):
            raise ValueError(f"Já existe uma organização chamada {nome}.")
        return nome

    def cria(self, nome: str, por: str = "", tipo: str = "instituicao", pai: Optional[str] = None) -> dict:
        """Cria sem ninguém dentro: quem entra (e quem administra) é decidido por app/acesso.py."""
        if tipo not in TIPOS:
            raise ValueError("Tipo de organização inválido.")
        lista = self._carrega()
        nome = self.valida_nome(nome, lista)
        if pai and not any(o["id"] == pai for o in lista):
            raise ValueError("Organização parceira (pai) não encontrada.")
        o = {"id": secrets.token_hex(6), "nome": nome, "tipo": tipo, "plano": None, "convite": secrets.token_hex(4).upper(),
             "admins": [], "membros": [], "pai": pai, "criado_em": agora_iso(), "criado_por": por}
        lista.append(o)
        self._grava(lista)
        return o

    def _altera(self, oid: str, muda) -> dict:
        lista = self._carrega()
        for o in lista:
            if o["id"] == oid:
                muda(o, lista)
                self._grava(lista)
                return o
        raise ValueError("Organização não encontrada.")

    def renomeia(self, oid: str, nome: str) -> dict:
        return self._altera(oid, lambda o, lista: o.update(nome=self.valida_nome(nome, lista, ignorar=oid)))

    def define_tipo(self, oid: str, tipo: str) -> dict:
        if tipo not in TIPOS:
            raise ValueError("Tipo de organização inválido.")
        return self._altera(oid, lambda o, _: o.update(tipo=tipo))

    def novo_convite(self, oid: str) -> dict:
        """Troca o código: quem tinha o antigo não entra mais."""
        return self._altera(oid, lambda o, _: o.update(convite=secrets.token_hex(4).upper()))

    def adiciona_membro(self, oid: str, uid: str, admin: bool = False) -> dict:
        """Entra como membro (e, se pedido, como administrador). Repetir não duplica."""
        if not uid:
            raise ValueError("Conta não informada.")

        def muda(o, _):
            if uid not in o["membros"]:
                o["membros"].append(uid)
            if admin and uid not in o["admins"]:
                o["admins"].append(uid)

        return self._altera(oid, muda)

    def define_admin(self, oid: str, uid: str, admin: bool) -> dict:
        """Dá ou tira a administração da organização (o administrador não precisa ser membro)."""
        if not uid:
            raise ValueError("Conta não informada.")

        def muda(o, _):
            if admin and uid not in o["admins"]:
                o["admins"].append(uid)
            if not admin and uid in o["admins"]:
                o["admins"].remove(uid)

        return self._altera(oid, muda)

    def remove_membro(self, oid: str, uid: str) -> dict:
        """Sai da organização: deixa de ser membro e de administrar."""
        def muda(o, _):
            o["membros"] = [x for x in o["membros"] if x != uid]
            o["admins"] = [x for x in o["admins"] if x != uid]

        return self._altera(oid, muda)

    def remove(self, oid: str) -> None:
        lista = self._carrega()
        if not any(o["id"] == oid for o in lista):
            raise ValueError("Organização não encontrada.")
        self._grava([o for o in lista if o["id"] != oid])
