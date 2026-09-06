"""Organizações: uma editora ou instituição agrupa contas de cliente.

Quem está na mesma organização vê os mesmos documentos e as mesmas revistas (as que a organização cadastrou).
Documento e revista guardam `organizacao` (o id) quando são criados por alguém que está numa; o que foi criado
antes de entrar continua só da pessoa. Entrar numa organização é por código de convite (ou pelo administrador,
em Usuários); ninguém entra digitando o nome, porque isso abriria os documentos dos outros.

Armazenamento: XMLJATS_DATA/organizacoes.json — lista de {id, nome, convite, criado_em, criado_por}.
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


def normaliza_convite(codigo: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", (codigo or "").upper())


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
        return dados.get("organizacoes", []) if isinstance(dados, dict) else (dados or [])

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

    # ------------------------------------------------------------ mudanças
    @staticmethod
    def valida_nome(nome: str, existentes: list, ignorar: Optional[str] = None) -> str:
        nome = " ".join((nome or "").split())
        if not RE_NOME.match(nome):
            raise ValueError("Nome da organização: de 3 a 80 caracteres.")
        if any(o["nome"].lower() == nome.lower() and o["id"] != ignorar for o in existentes):
            raise ValueError(f"Já existe uma organização chamada {nome}.")
        return nome

    def cria(self, nome: str, por: str = "") -> dict:
        lista = self._carrega()
        nome = self.valida_nome(nome, lista)
        o = {"id": secrets.token_hex(6), "nome": nome, "convite": secrets.token_hex(4).upper(),
             "criado_em": agora_iso(), "criado_por": por}
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

    def novo_convite(self, oid: str) -> dict:
        """Troca o código: quem tinha o antigo não entra mais."""
        return self._altera(oid, lambda o, _: o.update(convite=secrets.token_hex(4).upper()))

    def remove(self, oid: str) -> None:
        lista = self._carrega()
        if not any(o["id"] == oid for o in lista):
            raise ValueError("Organização não encontrada.")
        self._grava([o for o in lista if o["id"] != oid])
