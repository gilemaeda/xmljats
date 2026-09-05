"""Entrega a SciELO: conferencia do pacote, deposito por FTP (servidor local de verdade) e e-mails obrigatorios."""
import io
import json
import os
import shutil
import sys
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
r = c2.post(f"/doc/{doc}/editar", data=form)
ok(r.status_code == 303, "documento completo e validado")
val = json.load(io.open(pasta / "validacao.json", encoding="utf-8"))
ok(val.get("pronto") is True, f"documento pronto para entrega (pronto={val.get('pronto')})")

# ---------------------------------------------------------------- pacote e conferência
z = c2.get(f"/doc/{doc}/pacote.zip")
ok(z.status_code == 200, "pacote .zip baixa")
with zipfile.ZipFile(io.BytesIO(z.content)) as arq:
    nomes = arq.namelist()
ok(all("/" not in n for n in nomes), f"arquivos na raiz do .zip: {nomes}")
ok(any(n.endswith("-relatorio.html") for n in nomes), "relatório de validação vai dentro do pacote")
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
if aviso:
    ok("2179-8966" in aviso["texto"] and zipe.stem in aviso["texto"], "o aviso traz ISSN e nome do pacote")
    ok("Entrega" in aviso["texto"], "o aviso diz em que pasta foi depositado")

# correção vai para a outra pasta
r = c.post(f"/doc/{doc}/entrega", data={"correcao": "1"})
ok(os.path.exists(os.path.join(ftproot, "Correcao", zipe.name)), "correção vai para a pasta Correcao")

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
