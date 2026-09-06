"""Entrega a SciELO: conferencia do pacote, deposito por FTP (servidor local de verdade) e e-mails obrigatorios."""
import io
import json
import os
import re
import shutil
import sys
if hasattr(sys.stdout, "reconfigure"):  # console cp1252 do Windows nao imprime todo Unicode e derrubava o teste
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import tempfile
import threading
import zipfile

tmp = tempfile.mkdtemp(prefix="xmljats-entrega-")
ftproot = tempfile.mkdtemp(prefix="xmljats-ftp-")
os.environ["XMLJATS_DATA"] = tmp
os.environ["APP_SENHA"] = "senha-de-teste-123"
sys.path.insert(0, r"C:\Users\gilej\PROJETOS\XML")
sys.path.insert(0, r"C:\Users\gilej\PROJETOS\XML\app")
from fastapi.testclient import TestClient  # noqa: E402
import app.main as M  # noqa: E402
from app.main import app  # noqa: E402
import entrega as E  # noqa: E402

falhas = []


def ok(cond, msg):
    print(("ok   " if cond else "FALHA"), msg)
    if not cond:
        falhas.append(msg)


# ---------------------------------------------------------------- servidor FTP local, para provar o deposito
from pyftpdlib.authorizers import DummyAuthorizer  # noqa: E402
from pyftpdlib.handlers import FTPHandler  # noqa: E402
from pyftpdlib.servers import FTPServer  # noqa: E402

os.makedirs(os.path.join(ftproot, "Entrega"), exist_ok=True)
os.makedirs(os.path.join(ftproot, "Correcao"), exist_ok=True)
aut = DummyAuthorizer()
aut.add_user("provedor", "segredo-do-ftp", ftproot, perm="elradfmwMT")
handler = FTPHandler
handler.authorizer = aut
servidor = FTPServer(("127.0.0.1", 0), handler)
PORTA_FTP = servidor.socket.getsockname()[1]
threading.Thread(target=servidor.serve_forever, kwargs={"timeout": 0.2}, daemon=True).start()
print(f"     servidor FTP de teste em 127.0.0.1:{PORTA_FTP}, raiz {ftproot}")

# ---------------------------------------------------------------- regras de nome do guia
ok(E.confere_nome("2179-8966-rdp-17-03-e92016.xml") is None, "nome no padrão SPS é aceito")
ok("acento" in (E.confere_nome("artigo-ção.xml") or ""), "nome com acento é recusado")
ok("underline" in (E.confere_nome("artigo_1.xml") or ""), "nome com underline é recusado")
ok("ponto" in (E.confere_nome("artigo.v2.xml") or ""), "nome com ponto extra é recusado")
ok("espaço" in (E.confere_nome("meu artigo.xml") or ""), "nome com espaço é recusado")
ok("extensão" in (E.confere_nome("pacote.rar") or ""), ".rar não está na lista de formatos do guia")
ok(E.confere_nome_pasta("2179-8966-rdp-17-03-0126") is None and "underline" in (E.confere_nome_pasta("rdp_17") or "")
   and "ponto" in (E.confere_nome_pasta("rdp.17") or ""), "regras de nome de pasta (SPS 1.10)")

# ---------------------------------------------------------------- nome do pacote, lote e título do e-mail (SPS 1.10)
REV_PC = {"acronimo": "scie", "issn_epub": "0124-4567", "modo_publicacao": "continua"}
REV_REG = dict(REV_PC, modo_publicacao="regular")
DOC = {"volume": "10", "numero": "3", "ano": "2025"}
ok(E.codigo_lote(3, "2025") == "0325" and E.codigo_lote(47, "2026") == "4726" and E.codigo_lote(103, "2026") == "10326",
   "código do lote: sequência com dois dígitos + dois do ano (0325, 4726, 10326)")
ok(E.nome_pasta(REV_PC, DOC, 1) == "0124-4567-scie-10-03-0125", f"pasta em publicação contínua: {E.nome_pasta(REV_PC, DOC, 1)}")
ok(E.nome_pasta(REV_REG, DOC) == "0124-4567-scie-10-03", f"pasta na modalidade regular: {E.nome_pasta(REV_REG, DOC)}")
ok(E.nome_pasta(REV_PC, DOC, None) is None, "publicação contínua sem lote não tem nome de pasta")
ok(E.identificador_entrega(REV_PC, DOC, 16, "BR") == "scie v10n3 Lote 1625 - BR", "identificador em publicação contínua")
ok(E.identificador_entrega(REV_REG, DOC, None, "BR/PS") == "scie v10n3 2025 - BR/PS", "identificador na modalidade regular")
ok(E.titulo_email(REV_REG, dict(DOC, ano="2026"), None, "BR") == "Entrega | scie v10n3 2026 - BR", "título do e-mail de atualização")
ok(E.titulo_email(REV_REG, dict(DOC, ano="1999"), None, "RE") == "Retrô Entrega | scie v10n3 1999 - RE", "pacote retrospectivo vira 'Retrô Entrega |'")
ok(E.ano_do_volume({"datas": {"publicado": "2026-02-10"}}) == "2026", "sem 'ano', o ano do volume sai da data de publicação")
ok(E.caminho_ftp({"tipo_conta": "prestador"}, "rdp") == "Entrega" and E.caminho_ftp({"tipo_conta": "scielo"}, "rdp") == "rdp/Entrega"
   and E.caminho_ftp({"tipo_conta": "scielo"}, "rdp", True) == "rdp/Correcao", "pasta no FTP conforme o tipo de conta")
_a, _c = E.email_deposito(REV_PC, dict(DOC, titulo="T", doi="10.1/x"), 1, "BR", "0124-4567-scie-10-03-0125.zip", "Entrega")
ok(_a == "Entrega | scie v10n3 Lote 0125 - BR" and "Informo que o .zip com a marcação XML do periódico “scie v10n3 Lote 0125 - BR”, foi disponibilizado no FTP." in _c
   and "- Total de XMLs = 1." in _c, "corpo do e-mail começa com a frase fixa da SPS 1.10")

# ---------------------------------------------------------------- documento de verdade
c = TestClient(app, follow_redirects=False)
r = c.post("/entrar", data={"email": "admin", "senha": "senha-de-teste-123", "proximo": "/"})
c.cookies.set("xmljats_sessao", r.cookies["xmljats_sessao"])
c2 = TestClient(app, follow_redirects=False)
r = c2.post("/registrar", data={"nome": "Cliente", "email": "cli@exemplo.org", "senha": "senha-forte-1", "senha2": "senha-forte-1"})
c2.cookies.set("xmljats_sessao", r.cookies["xmljats_sessao"])
with open(r"C:\Users\gilej\PROJETOS\XML\modelos\Direito e Praxis.pdf", "rb") as f:
    r = c2.post("/validar", files={"arquivo": ("a.pdf", f, "application/pdf")}, data={"revista": "rdp", "sps": "1.9"})
doc = r.headers["location"].rsplit("/", 1)[-1]
pasta = __import__("pathlib").Path(tmp) / "docs" / doc

# completa os obrigatórios para o documento ficar pronto
modelo = M.modelo_efetivo(pasta)
revista = next(x for x in M.carrega_revistas() if x["acronimo"] == "rdp")
pend = M.obrigatorios.pendencias(modelo, revista)
form = {"acao": "salvar", "revista": "rdp"}
for k, val in M.valores_editaveis(modelo).items():
    form[k] = val
for campo in pend:
    if campo.startswith("data_"):
        form[campo] = "2026-02-10"
    elif campo == "order":
        form[campo] = "92016"
    elif campo == "licenca":
        form[campo] = "CC BY 4.0"
    elif campo == "_referencias":
        continue
    else:
        form.setdefault(campo, "Preenchido")
form["ano"] = "2026"  # ano do volume: entra no lote e no título do e-mail
r = c2.post(f"/doc/{doc}/editar", data=form)
ok(r.status_code == 303, "documento completo e validado")
val = json.load(io.open(pasta / "validacao.json", encoding="utf-8"))
ok(val.get("pronto") is True, f"documento pronto para entrega (pronto={val.get('pronto')})")

# ---------------------------------------------------------------- pacote e conferência
z = c2.get(f"/doc/{doc}/pacote.zip")
ok(z.status_code == 200, "pacote .zip baixa")
with zipfile.ZipFile(io.BytesIO(z.content)) as arq:
    nomes = arq.namelist()
topos = {n.split("/")[0] for n in nomes}
ok(len(topos) == 1 and all("/" in n for n in nomes) and re.match(r"^2179-8966-rdp-17-03-01\d\d$", next(iter(topos))),
   f"uma pasta com o nome do pacote (ISSN-acrônimo-volume-número-lote) dentro do .zip: {nomes}")
ok(any(n.endswith("/xpm.html") for n in nomes), "relatório de validação xpm.html dentro da pasta")
ok(z.headers.get("content-disposition", "").endswith(f'{next(iter(topos))}.zip"'), "o .zip baixa com o nome da pasta")
ok(any(n.endswith(".xml") for n in nomes) and any(n.endswith(".pdf") for n in nomes), "XML e PDF no pacote")

pag = c.get(f"/doc/{doc}/entrega").text
ok("Conferência do pacote" in pag and "Depositar no FTP" in pag, "tela de entrega abre")
ok("publicacao@scielo.org" in pag, "a tela diz o endereço obrigatório do aviso")
ok("MathML ou LaTeX" in pag, "a tela lembra a exigência de fórmula codificada")
ok("Atestado de capacidade técnica" in pag and "6 meses" in pag, "a tela explica o atestado (selo)")

zipe = M.caminho_pacote(pasta)
conf = E.confere_pacote(str(zipe))
for i in conf["itens"]:
    print(f"     {'ok ' if i['ok'] else 'X  '} {i['que']}: {i['detalhe'][:90]}")
ok(conf["ok"], "pacote gerado passa na conferência do guia")

# ---------------------------------------------------------------- FTP não configurado
r = c.post(f"/doc/{doc}/entrega")
ok(r.status_code == 303 and "erro" in r.headers["location"], "sem FTP configurado, o depósito é recusado com explicação")
ok("publicacao%40scielo.org" in r.headers["location"] or "publicacao" in r.headers["location"],
   "a recusa diz a quem pedir as credenciais")

# ---------------------------------------------------------------- configura e testa o FTP
r = c.post("/admin/config/ftp", data={"servidor": "ftp.exemplo.org/pasta", "usuario": "x", "senha": "y"})
ok("erro" in r.headers["location"], "servidor com barra é recusado")
r = c.post("/admin/config/ftp", data={"servidor": "127.0.0.1", "porta": str(PORTA_FTP), "usuario": "provedor",
                                      "senha": "segredo-do-ftp", "pasta_entrega": "Entrega", "pasta_correcao": "Correcao"})
ok(r.status_code == 303 and "mensagem" in r.headers["location"], "credenciais do FTP salvas")
cfg = json.load(io.open(os.path.join(tmp, "config.json"), encoding="utf-8"))
ok(cfg["scielo_ftp"]["senha"] == "segredo-do-ftp", "senha do FTP gravada só no config.json do servidor")
pag = c.get("/admin/config").text
ok("segredo-do-ftp" not in pag, "a senha do FTP nunca aparece inteira na tela")
ok("FTP da SciELO" in pag and "Atestado de capacidade técnica" in pag, "configurações mostram FTP e atestado")

r = c.post("/admin/config/ftp/testar")
ok("mensagem" in r.headers["location"] and "Entrega" in r.headers["location"], "teste de conexão lista as pastas do servidor")

# senha em branco mantém a salva
c.post("/admin/config/ftp", data={"servidor": "127.0.0.1", "porta": str(PORTA_FTP), "usuario": "provedor", "senha": ""})
cfg = json.load(io.open(os.path.join(tmp, "config.json"), encoding="utf-8"))
ok(cfg["scielo_ftp"]["senha"] == "segredo-do-ftp", "senha em branco no formulário mantém a senha salva")

# ---------------------------------------------------------------- e-mail da equipe editorial entra em cópia
rdp = next(x for x in M.carrega_revistas() if x["acronimo"] == "rdp")
form_rev = {k: v for k, v in rdp.items() if isinstance(v, str)}
form_rev["na_scielo"] = "sim" if rdp.get("na_scielo") else "nao"
form_rev["email_editorial"] = "editoria@rdp.org"
r = c.post("/revistas/rdp", data=form_rev)
ok(r.status_code == 303 and "erro" not in r.headers.get("location", ""), f"cadastro da revista aceita o e-mail editorial ({r.status_code})")

# ---------------------------------------------------------------- depósito de verdade
r = c.post(f"/doc/{doc}/entrega")
ok(r.status_code == 303 and "mensagem" in r.headers["location"], f"depósito aceito: {r.headers['location'][:120]}")
depositado = os.path.join(ftproot, "Entrega", zipe.name)
ok(os.path.exists(depositado), f"o arquivo chegou no FTP ({zipe.name})")
ok(os.path.getsize(depositado) == os.path.getsize(zipe), "o arquivo chegou inteiro")
cfg_doc = json.load(io.open(pasta / "config.json", encoding="utf-8"))
ok(cfg_doc.get("etapa") == "entregue", "a etapa do documento vira 'entregue'")
ok(cfg_doc.get("entrega", {}).get("arquivo") == zipe.name, "o depósito fica registrado no documento")

rascunhos = M.CORREIO.lista("rascunhos")
aviso = next((m for m in rascunhos if E.EMAIL_SCIELO in m["para"]), None)
ok(aviso is not None, "o aviso obrigatório fica como rascunho no correio")
ok(aviso is not None and "editoria@rdp.org" in aviso["para"], f"a equipe editorial da revista entra em cópia: {aviso and aviso['para']}")
if aviso:
    ok(re.match(r"^Entrega \| rdp v17n3 Lote 01\d\d - BR$", aviso["assunto"]), f"título no formato da SPS 1.10: {aviso['assunto']}")
    ok("Informo que o .zip com a marcação XML do periódico “rdp v17n3 Lote 01" in aviso["texto"] and "- Total de XMLs = 1." in aviso["texto"],
       "corpo começa pela frase fixa e informa o total de XMLs")
ok(re.match(r"^2179-8966-rdp-17-03-01\d\d\.zip$", zipe.name), f"o .zip depositado tem o nome da pasta: {zipe.name}")
lotes = json.load(io.open(os.path.join(tmp, "lotes.json"), encoding="utf-8"))
ok(lotes.get("rdp|17|3", {}).get("proximo") == 2, f"o registro de lotes avança para o próximo: {lotes.get('rdp|17|3')}")
ok(json.load(io.open(pasta / "config.json", encoding="utf-8")).get("lote") == 1, "o lote fica gravado no documento")
ok("Lote 01" in c.get(f"/doc/{doc}/entrega").text, "a tela de entrega mostra o lote")
if aviso:
    ok("2179-8966" in aviso["texto"] and zipe.stem in aviso["texto"], "o aviso traz ISSN e nome do pacote")
    ok("Entrega" in aviso["texto"], "o aviso diz em que pasta foi depositado")

# correção vai para a outra pasta
r = c.post(f"/doc/{doc}/entrega", data={"correcao": "1"})
ok(os.path.exists(os.path.join(ftproot, "Correcao", zipe.name)), "correção vai para a pasta Correcao")
ok(json.load(io.open(os.path.join(tmp, "lotes.json"), encoding="utf-8")).get("rdp|17|3", {}).get("proximo") == 2,
   "correção não consome lote novo")

# conta da própria revista no FTP da SciELO: deposita em <acrônimo>/Entrega
os.makedirs(os.path.join(ftproot, "rdp", "Entrega"), exist_ok=True)
os.makedirs(os.path.join(ftproot, "rdp", "Correcao"), exist_ok=True)
r = c.post("/admin/config/ftp", data={"servidor": "127.0.0.1", "porta": str(PORTA_FTP), "usuario": "provedor", "senha": "",
                                      "tipo_conta": "scielo", "colecao_sigla": "br/sp"})
ok(r.status_code == 303 and "mensagem" in r.headers["location"], "tipo de conta e sigla da coleção salvos")
ok(E.config_ftp(M.CORREIO.config())["colecao_sigla"] == "BR/SP", "a sigla é guardada em maiúsculas")
r = c.post("/admin/config/ftp", data={"servidor": "127.0.0.1", "porta": str(PORTA_FTP), "usuario": "provedor", "senha": "",
                                      "colecao_sigla": "XX"})
ok("erro" in r.headers["location"], "sigla de coleção desconhecida é recusada")
r = c.post(f"/doc/{doc}/entrega")
ok(r.status_code == 303 and "mensagem" in r.headers["location"], "depósito pela conta da revista aceito")
ok(os.path.exists(os.path.join(ftproot, "rdp", "Entrega", zipe.name)), "com a conta da revista, o pacote vai para rdp/Entrega")
avisos = [m["assunto"] for m in M.CORREIO.lista("rascunhos") if E.EMAIL_SCIELO in m["para"]]
ok(any(a.endswith(" - BR/SP") for a in avisos), f"o título usa a sigla configurada: {avisos}")
ok("rdp/Entrega" in c.get(f"/doc/{doc}/entrega").text, "a tela mostra a pasta acrônimo/Entrega")

# ---------------------------------------------------------------- pedido do atestado
r = c.post("/admin/config/atestado", data={"empresa": "", "cnpj": ""})
ok("erro" in r.headers["location"], "atestado sem empresa e CNPJ é recusado (a SciELO só avalia pessoa jurídica)")
r = c.post("/admin/config/atestado", data={"empresa": "Provedora XML Ltda", "cnpj": "00.000.000/0001-00", "contato": "g@e.org"})
ok(r.status_code == 303 and "rascunhos" in r.headers["location"], "pedido do atestado vira rascunho")
pedido = next((m for m in M.CORREIO.lista("rascunhos") if "atestado" in m["assunto"].lower()), None)
ok(pedido is not None and "00.000.000/0001-00" in (pedido or {}).get("texto", ""), "o pedido traz empresa e CNPJ")
ok("15 dias" in (pedido or {}).get("texto", ""), "o pedido registra o prazo de 15 dias da amostra")

# ---------------------------------------------------------------- credenciais erradas
c.post("/admin/config/ftp", data={"servidor": "127.0.0.1", "porta": str(PORTA_FTP), "usuario": "provedor", "senha": "errada"})
r = c.post(f"/doc/{doc}/entrega")
ok(r.status_code == 303 and "erro" in r.headers["location"], "senha errada devolve erro em vez de quebrar")

servidor.close_all()
print("\nFALHAS:", len(falhas))
for f in falhas:
    print("  -", f)
shutil.rmtree(tmp, ignore_errors=True)
shutil.rmtree(ftproot, ignore_errors=True)
sys.exit(1 if falhas else 0)
