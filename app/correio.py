"""
Correio do xmljats: configuração do Resend, caixas (entrada, saída, enviados, rascunhos, lixeira) e confirmação de conta.

Armazenamento (tudo em XMLJATS_DATA, fora do git):
  config.json      configuração do sistema, incluindo a chave da API do Resend (nunca é devolvida inteira para a tela)
  correio.json     mensagens, cada uma com caixa, remetente, destinatários, assunto, corpo, estado e histórico

Envio: POST https://api.resend.com/emails com "Authorization: Bearer <chave>". Uma mensagem nasce em "saida"; quando o
Resend aceita, vai para "enviados" com o id devolvido; se falha, volta para "saida" com o erro e pode ser reenviada.
Eventos (entregue, aberto, devolvido) chegam pelo webhook /webhook/resend e entram no histórico da mensagem.
Entrada: o Resend Inbound entrega o e-mail recebido no mesmo webhook; ele vira mensagem na caixa "entrada".

Sem chave configurada nada é enviado: a mensagem fica na caixa de saída, e a tela diz por quê. Nada é inventado.
"""
import io
import json
import os
import re
import secrets
import urllib.error
import urllib.request
from pathlib import Path
from typing import List, Optional

from tempo import agora_iso  # noqa: E402  (app/tempo.py)

CAIXAS = [("entrada", "Caixa de entrada"), ("saida", "Caixa de saída"), ("enviados", "Enviados"),
          ("rascunhos", "Rascunhos"), ("lixeira", "Lixeira")]
ROTULO_CAIXA = dict(CAIXAS)
API = "https://api.resend.com/emails"
RE_EMAIL_SIMPLES = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _le(caminho: Path, padrao):
    if not caminho.exists():
        return padrao
    try:
        with io.open(caminho, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return padrao


def _grava(caminho: Path, obj):
    caminho.parent.mkdir(parents=True, exist_ok=True)
    tmp = caminho.with_suffix(".tmp")
    with io.open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
    os.replace(tmp, caminho)


def mascara(chave: Optional[str]) -> str:
    """re_1234abcd… -> 're_1234…cd' (para a tela nunca mostrar a chave inteira)."""
    if not chave:
        return ""
    return chave[:7] + "…" + chave[-2:] if len(chave) > 12 else "…"


class Correio:
    def __init__(self, pasta_dados: Path):
        self.pasta = Path(pasta_dados)
        self.arq_config = self.pasta / "config.json"
        self.arq_msgs = self.pasta / "correio.json"

    # ------------------------------------------------------------ configuração
    def config(self) -> dict:
        c = _le(self.arq_config, {}) or {}
        c.setdefault("resend_chave", "")
        c.setdefault("remetente_email", "")
        c.setdefault("remetente_nome", "xmljats")
        c.setdefault("url_base", "")
        c.setdefault("exigir_confirmacao", False)
        if not c.get("webhook_segredo"):
            # o segredo nasce com o sistema: sem ele, qualquer um poderia injetar mensagens pelo webhook
            c["webhook_segredo"] = secrets.token_urlsafe(24)
            _grava(self.arq_config, c)
        return c

    def config_publica(self) -> dict:
        """Config para a tela: a chave vai mascarada e há um resumo do que falta para o envio funcionar."""
        c = dict(self.config())
        c["resend_chave_mascarada"] = mascara(c["resend_chave"])
        c["tem_chave"] = bool(c["resend_chave"])
        c.pop("resend_chave", None)
        c["pronto_para_enviar"] = bool(c["tem_chave"] and c["remetente_email"])
        pend = []
        if not c["tem_chave"]:
            pend.append("chave da API do Resend")
        if not c["remetente_email"]:
            pend.append("e-mail remetente (de um domínio verificado no Resend)")
        if not c["url_base"]:
            pend.append("endereço público do site (para o link de confirmação)")
        c["pendencias"] = pend
        return c

    def salva_config(self, dados: dict):
        c = self.config()
        if dados.get("resend_chave"):  # campo em branco = manter a chave atual
            c["resend_chave"] = dados["resend_chave"].strip()
        if dados.get("remover_chave"):
            c["resend_chave"] = ""
        for k in ("remetente_email", "remetente_nome", "url_base"):
            if k in dados:
                c[k] = (dados.get(k) or "").strip()
        if c["remetente_email"] and not RE_EMAIL_SIMPLES.match(c["remetente_email"]):
            raise ValueError("O e-mail remetente precisa ser um endereço válido.")
        if c["url_base"] and not re.match(r"^https?://", c["url_base"]):
            raise ValueError("O endereço do site precisa começar com http:// ou https://.")
        c["url_base"] = c["url_base"].rstrip("/")
        c["exigir_confirmacao"] = bool(dados.get("exigir_confirmacao"))
        if c["exigir_confirmacao"] and not (c["resend_chave"] and c["remetente_email"]):
            raise ValueError("Para exigir confirmação por e-mail, configure antes a chave do Resend e o remetente.")
        if not c.get("webhook_segredo"):
            c["webhook_segredo"] = secrets.token_urlsafe(24)
        _grava(self.arq_config, c)
        return self.config_publica()

    # ------------------------------------------------------------ mensagens
    def _todas(self) -> List[dict]:
        return _le(self.arq_msgs, {"mensagens": []}).get("mensagens", [])

    def _salva_todas(self, msgs):
        _grava(self.arq_msgs, {"mensagens": msgs})

    def lista(self, caixa: str = "entrada", busca: str = "") -> List[dict]:
        msgs = [m for m in self._todas() if m.get("caixa") == caixa]
        if busca:
            b = busca.lower()
            msgs = [m for m in msgs if b in (m.get("assunto", "") + " " + " ".join(m.get("para", [])) +
                                             " " + m.get("de", "") + " " + m.get("texto", "")).lower()]
        msgs.sort(key=lambda m: m.get("em", ""), reverse=True)
        return msgs

    def contagens(self) -> dict:
        msgs = self._todas()
        out = {c: sum(1 for m in msgs if m.get("caixa") == c) for c, _ in CAIXAS}
        out["nao_lidas"] = sum(1 for m in msgs if m.get("caixa") == "entrada" and not m.get("lida"))
        return out

    def por_id(self, mid: str) -> Optional[dict]:
        return next((m for m in self._todas() if m["id"] == mid), None)

    def _muda(self, mid: str, funcao):
        msgs = self._todas()
        for m in msgs:
            if m["id"] == mid:
                funcao(m)
                self._salva_todas(msgs)
                return m
        raise ValueError("Mensagem não encontrada.")

    def marca_lida(self, mid: str, lida: bool = True):
        return self._muda(mid, lambda m: m.update(lida=lida))

    def move(self, mid: str, caixa: str):
        if caixa not in ROTULO_CAIXA:
            raise ValueError("Caixa inválida.")
        return self._muda(mid, lambda m: m.update(caixa=caixa))

    def apaga(self, mid: str):
        msgs = [m for m in self._todas() if m["id"] != mid]
        self._salva_todas(msgs)

    def cria(self, para, assunto: str, texto: str, html: str = "", caixa: str = "rascunhos",
             tipo: str = "manual", por: str = "", responde_a: str = "") -> dict:
        if isinstance(para, str):
            para = [x.strip() for x in re.split(r"[,;]", para) if x.strip()]
        invalidos = [p for p in para if not RE_EMAIL_SIMPLES.match(p)]
        if invalidos:
            raise ValueError("Endereço inválido: " + ", ".join(invalidos))
        if not para:
            raise ValueError("Informe ao menos um destinatário.")
        if not (assunto or "").strip():
            raise ValueError("Informe o assunto.")
        c = self.config()
        m = {"id": secrets.token_hex(8), "caixa": caixa, "tipo": tipo,
             "de": f"{c['remetente_nome']} <{c['remetente_email']}>" if c["remetente_email"] else "",
             "para": para, "assunto": assunto.strip(), "texto": texto or "", "html": html or "",
             "em": agora_iso(), "por": por, "lida": caixa != "entrada", "estado": "rascunho",
             "historico": [{"quando": agora_iso(), "evento": "criada", "por": por}], "responde_a": responde_a}
        msgs = self._todas()
        msgs.append(m)
        self._salva_todas(msgs)
        return m

    # ------------------------------------------------------------ envio
    def _post_resend(self, chave: str, corpo: dict):
        req = urllib.request.Request(API, data=json.dumps(corpo).encode("utf-8"), method="POST",
                                     headers={"Authorization": "Bearer " + chave, "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode("utf-8") or "{}")

    def envia(self, mid: str, por: str = "") -> dict:
        """Manda a mensagem pelo Resend. Sem configuração, ela fica na caixa de saída com o motivo."""
        m = self.por_id(mid)
        if not m:
            raise ValueError("Mensagem não encontrada.")
        c = self.config()
        if not c["resend_chave"] or not c["remetente_email"]:
            return self._muda(mid, lambda x: x.update(
                caixa="saida", estado="sem configuração",
                erro="Configure a chave do Resend e o e-mail remetente em Configurações para enviar.",
                historico=x["historico"] + [{"quando": agora_iso(), "evento": "envio bloqueado: sem configuração", "por": por}]))
        corpo = {"from": f"{c['remetente_nome']} <{c['remetente_email']}>", "to": m["para"], "subject": m["assunto"]}
        if m.get("html"):
            corpo["html"] = m["html"]
        corpo["text"] = m.get("texto") or ""
        try:
            resp = self._post_resend(c["resend_chave"], corpo)
        except urllib.error.HTTPError as e:
            detalhe = e.read().decode("utf-8", "ignore")[:300]
            return self._muda(mid, lambda x: x.update(
                caixa="saida", estado="falhou", erro=f"HTTP {e.code}: {detalhe}",
                historico=x["historico"] + [{"quando": agora_iso(), "evento": f"falha no envio (HTTP {e.code})", "por": por}]))
        except Exception as e:  # noqa: BLE001
            return self._muda(mid, lambda x: x.update(
                caixa="saida", estado="falhou", erro=str(e)[:300],
                historico=x["historico"] + [{"quando": agora_iso(), "evento": "falha no envio", "por": por}]))
        return self._muda(mid, lambda x: x.update(
            caixa="enviados", estado="enviado", erro=None, resend_id=resp.get("id"),
            de=corpo["from"], enviado_em=agora_iso(),
            historico=x["historico"] + [{"quando": agora_iso(), "evento": "enviado pelo Resend", "por": por}]))

    def envia_novo(self, para, assunto, texto, html="", tipo="manual", por="") -> dict:
        m = self.cria(para, assunto, texto, html, caixa="saida", tipo=tipo, por=por)
        return self.envia(m["id"], por=por)

    def reenvia_pendentes(self, por: str = "sistema") -> int:
        n = 0
        for m in self.lista("saida"):
            r = self.envia(m["id"], por=por)
            n += 1 if r.get("caixa") == "enviados" else 0
        return n

    # ------------------------------------------------------------ webhook (eventos e entrada)
    def registra_evento(self, dados: dict) -> str:
        """Evento do Resend: liga ao envio pelo id, ou cria mensagem na entrada quando é e-mail recebido."""
        tipo = (dados.get("type") or "").lower()
        d = dados.get("data") or {}
        rid = d.get("email_id") or d.get("id")
        if tipo.startswith("email.") and rid:
            msgs = self._todas()
            for m in msgs:
                if m.get("resend_id") == rid:
                    m.setdefault("historico", []).append({"quando": agora_iso(), "evento": tipo.replace("email.", "")})
                    m["estado"] = tipo.replace("email.", "")
                    self._salva_todas(msgs)
                    return f"evento {tipo} registrado"
        if tipo in ("email.received", "inbound.email", "email.inbound"):
            para = d.get("to") or []
            if isinstance(para, str):
                para = [para]
            m = {"id": secrets.token_hex(8), "caixa": "entrada", "tipo": "recebida",
                 "de": d.get("from") or "", "para": para, "assunto": d.get("subject") or "(sem assunto)",
                 "texto": d.get("text") or "", "html": d.get("html") or "", "em": agora_iso(), "lida": False,
                 "estado": "recebida", "resend_id": rid, "historico": [{"quando": agora_iso(), "evento": "recebida"}]}
            msgs = self._todas()
            msgs.append(m)
            self._salva_todas(msgs)
            return "mensagem recebida"
        return f"evento ignorado ({tipo or 'sem tipo'})"


# ---------------------------------------------------------------- confirmação de conta

def token_confirmacao() -> str:
    return secrets.token_urlsafe(24)


def corpo_confirmacao(nome: str, link: str) -> tuple:
    texto = (f"Olá, {nome}.\n\nSua conta no xmljats foi criada. Confirme o endereço clicando no link abaixo:\n\n{link}\n\n"
             "Se não foi você quem se cadastrou, ignore esta mensagem.\n\nxmljats")
    html = (f"<p>Olá, {nome}.</p><p>Sua conta no <b>xmljats</b> foi criada. Confirme o endereço clicando no botão:</p>"
            f"<p><a href=\"{link}\" style=\"background:#1B3A66;color:#fff;padding:10px 16px;border-radius:8px;"
            f"text-decoration:none\">Confirmar meu e-mail</a></p><p>Ou abra este endereço: <br>{link}</p>"
            "<p style=\"color:#5C6979;font-size:13px\">Se não foi você quem se cadastrou, ignore esta mensagem.</p>")
    return texto, html
