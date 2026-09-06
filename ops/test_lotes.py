"""Lotes de entrega: até 5 artigos prontos da mesma revista e volume/número num só pacote, conferência de cada XML,
aviso com 'Total de XMLs = N', depósito num FTP de verdade, desfazer e regras de recusa."""
import io
import json
import os
import shutil
import sys
if hasattr(sys.stdout, "reconfigure"):  # console cp1252 do Windows nao imprime todo Unicode e derrubava o teste
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import tempfile
import threading
import urllib.parse
import zipfile

tmp = tempfile.mkdtemp(prefix="xmljats-lotes-")
ftproot = tempfile.mkdtemp(prefix="xmljats-ftp-")
os.environ["XMLJATS_DATA"] = tmp
os.environ["APP_SENHA"] = "senha-de-teste-123"
RAIZ = r"C:\Users\gilej\PROJETOS\XML"
sys.path.insert(0, RAIZ)
sys.path.insert(0, os.path.join(RAIZ, "poc"))
sys.path.insert(0, os.path.join(RAIZ, "app"))
os.chdir(RAIZ)
from fastapi.testclient import TestClient  # noqa: E402
import app.main as M  # noqa: E402
from app.main import app  # noqa: E402
import entrega as E  # noqa: E402
import lotes as L  # noqa: E402

falhas = []


def ok(cond, msg):
    print(("ok   " if cond else "FALHA"), msg)
    if not cond:
        falhas.append(msg)


# ---------------------------------------------------------------- servidor FTP local
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

adm = TestClient(app, follow_redirects=False)
r = adm.post("/entrar", data={"email": "admin", "senha": "senha-de-teste-123", "proximo": "/"}, headers={"x-forwarded-for": "10.6.6.1"})
adm.cookies.set("xmljats_sessao", r.cookies["xmljats_sessao"])
c = TestClient(app, follow_redirects=False)
r = c.post("/registrar", data={"nome": "Cliente", "email": "cli@exemplo.org", "senha": "senha-forte-1", "senha2": "senha-forte-1"},
           headers={"x-forwarded-for": "10.6.6.2"})
c.cookies.set("xmljats_sessao", r.cookies["xmljats_sessao"])
DOCS = os.path.join(tmp, "docs")
revista = next(x for x in M.carrega_revistas() if x["acronimo"] == "rdp")


def cfg_de(doc):
    return json.load(io.open(os.path.join(DOCS, doc, "config.json"), encoding="utf-8"))


def envia_e_completa(elocation, volume="17"):
    with open(os.path.join(RAIZ, "modelos", "Direito e Praxis.pdf"), "rb") as f:
        r = c.post("/validar", files={"arquivo": ("a.pdf", f, "application/pdf")}, data={"revista": "rdp", "sps": "1.10"})
    doc = r.headers["location"].rsplit("/", 1)[-1]
    pasta = __import__("pathlib").Path(DOCS) / doc
    modelo = M.modelo_efetivo(pasta)
    form = {"acao": "salvar", "revista": "rdp"}
    for k, val in M.valores_editaveis(modelo).items():
        form[k] = val
    for campo in M.obrigatorios.pendencias(modelo, revista):
        if campo.startswith("data_"):
            form[campo] = "2026-02-10"
        elif campo == "order":
            form[campo] = "92016"
        elif campo == "licenca":
            form[campo] = "CC BY 4.0"
        elif campo != "_referencias":
            form.setdefault(campo, "Preenchido")
    form["ano"] = "2026"
    form["elocation"] = elocation
    form["volume"] = volume
    r = c.post(f"/doc/{doc}/editar", data=form)
    val = json.load(io.open(pasta / "validacao.json", encoding="utf-8"))
    return doc, val


doc1, v1 = envia_e_completa("e92016")
doc2, v2 = envia_e_completa("e92017")
doc3, v3 = envia_e_completa("e92018", volume="18")
ok(v1.get("pronto") and v2.get("pronto") and v3.get("pronto"), "três artigos prontos (dois do v17 n3, um do v18)")
ok(v1["nome_base"] != v2["nome_base"], f"nomes-base distintos: {v1['nome_base']} / {v2['nome_base']}")
with open(os.path.join(RAIZ, "modelos", "Direito e Praxis.pdf"), "rb") as f:
    r = c.post("/validar", files={"arquivo": ("a.pdf", f, "application/pdf")}, data={"revista": "rdp", "sps": "1.10"})
doc_incompleto = r.headers["location"].rsplit("/", 1)[-1]

# ---------------------------------------------------------------- 1. candidatos e tela
grupos = L.candidatos()
ok(("rdp", "17", "3") in grupos and len(grupos[("rdp", "17", "3")]) == 2 and ("rdp", "18", "3") in grupos,
   f"prontos agrupados por revista e volume/número: {[(k, len(v)) for k, v in grupos.items()]}")
ok(doc_incompleto not in [d["id"] for g in grupos.values() for d in g], "documento com bloqueante não entra nos candidatos")
pg = adm.get("/admin/lotes").text
ok("Montar lote" in pg and v1["nome_base"] in pg and v2["nome_base"] in pg, "a página Lotes lista os prontos por grupo")
ok(c.get("/admin/lotes").status_code == 403, "cliente não acessa a página de lotes")

# ---------------------------------------------------------------- 2. recusas
r = adm.post("/admin/lotes", data={"doc": [doc1, doc3]})
ok("mesma revista" in urllib.parse.unquote(r.headers["location"]), "volumes diferentes não vão no mesmo lote")
r = adm.post("/admin/lotes", data={"doc": [doc1, doc_incompleto]})
ok("não está pronto" in urllib.parse.unquote(r.headers["location"]), "documento com bloqueante é recusado")
r = adm.post("/admin/lotes", data={"doc": [f"x{i}" for i in range(6)]})
ok("no máximo 5" in urllib.parse.unquote(r.headers["location"]), "mais de 5 XMLs é recusado antes de qualquer outra coisa")
r = adm.post("/admin/lotes", data={"lote": ""})
ok("pelo menos um" in urllib.parse.unquote(r.headers["location"]), "lote vazio é recusado")

# ---------------------------------------------------------------- 3. monta o lote
r = adm.post("/admin/lotes", data={"doc": [doc1, doc2], "lote": "1"})
ok(r.status_code == 303 and "/admin/lotes/2179-8966-rdp-17-03-0126" in r.headers["location"], f"lote montado com o nome da SPS 1.10: {r.headers.get('location', '')[:70]}")
pasta_lote = "2179-8966-rdp-17-03-0126"
zipe = L.caminho_zip(pasta_lote)
ok(zipe.exists(), "o .zip do lote fica em XMLJATS_DATA/lotes")
with zipfile.ZipFile(zipe) as z:
    nomes = z.namelist()
ok(len({n.split("/")[0] for n in nomes}) == 1 and all(n.startswith(pasta_lote + "/") for n in nomes), f"uma pasta com o nome do lote dentro do .zip: {nomes[:3]}")
ok(sum(n.endswith(".xml") for n in nomes) == 2 and sum(n.endswith(".pdf") for n in nomes) == 2 and any(n.endswith("/xpm.html") for n in nomes),
   f"dois XML, dois PDF e um xpm.html: {[n.split('/')[-1] for n in nomes]}")
with zipfile.ZipFile(zipe) as z:
    rel = z.read(pasta_lote + "/xpm.html").decode("utf-8")
ok(v1["nome_base"] in rel and v2["nome_base"] in rel and "2 artigo(s)" in rel, "o relatório do lote lista os dois artigos")
ok(cfg_de(doc1).get("lote_pasta") == pasta_lote and cfg_de(doc2).get("lote") == 1, "cada documento guarda o lote em que está")
ok(doc1 not in [d["id"] for g in L.candidatos().values() for d in g], "documento no lote sai dos candidatos")
r = adm.post("/admin/lotes", data={"doc": [doc1]})
ok("já está no lote" in urllib.parse.unquote(r.headers["location"]), "não entra em dois lotes")
conf = E.confere_pacote(str(zipe))
for i in conf["itens"]:
    print(f"     {'ok ' if i['ok'] else 'X  '} {i['que']}: {i['detalhe'][:80]}")
ok(conf["ok"], "o pacote do lote passa na conferência, com os dois XML validados")
tela = adm.get(f"/admin/lotes/{pasta_lote}").text
ok("Total de XMLs = 2." in tela and "Entrega | rdp v17n3 Lote 0126 - BR" in tela, "a tela do lote mostra o aviso no formato da SPS 1.10")
ok(adm.get(f"/admin/lotes/{pasta_lote}/pacote.zip").status_code == 200, "o .zip do lote baixa")
ok(adm.get("/admin/lotes/2179-8966-rdp-17-03-9999").status_code == 404 and adm.get("/admin/lotes/x_y").status_code == 404, "lote inexistente ou nome inválido dá 404")

# ---------------------------------------------------------------- 4. desfazer e montar de novo
r = adm.post(f"/admin/lotes/{pasta_lote}/desfazer")
ok(r.status_code == 303 and not zipe.exists() and not cfg_de(doc1).get("lote_pasta") and L.por_pasta(pasta_lote) is None, "desfazer apaga o .zip, solta os documentos e tira o registro")
r = adm.post("/admin/lotes", data={"doc": [doc1, doc2]})  # sem número: usa o próximo da sequência
ok("/admin/lotes/2179-8966-rdp-17-03-0126" in r.headers["location"], "sem número informado, o lote usa o próximo da sequência (01)")

# ---------------------------------------------------------------- 5. depósito de verdade
r = adm.post("/admin/config/ftp", data={"servidor": "127.0.0.1", "porta": str(PORTA_FTP), "usuario": "provedor",
                                        "senha": "segredo-do-ftp", "pasta_entrega": "Entrega", "pasta_correcao": "Correcao"})
ok(r.status_code == 303 and "mensagem" in r.headers["location"], "FTP configurado")
r = adm.post(f"/admin/lotes/{pasta_lote}/entrega")
ok(r.status_code == 303 and "mensagem" in r.headers["location"], f"depósito do lote aceito: {urllib.parse.unquote(r.headers['location'])[:120]}")
depositado = os.path.join(ftproot, "Entrega", pasta_lote + ".zip")
ok(os.path.exists(depositado) and os.path.getsize(depositado) == zipe.stat().st_size, "o lote chegou inteiro no FTP")
aviso = next((m for m in M.CORREIO.lista("rascunhos") if E.EMAIL_SCIELO in m["para"]), None)
ok(aviso is not None and aviso["assunto"] == "Entrega | rdp v17n3 Lote 0126 - BR" and "- Total de XMLs = 2." in aviso["texto"],
   f"aviso obrigatório com o título fixo e o total: {aviso and aviso['assunto']}")
ok(cfg_de(doc1).get("etapa") == "entregue" and cfg_de(doc2).get("etapa") == "entregue", "os dois artigos ficam 'entregues'")
ok(cfg_de(doc1).get("entrega", {}).get("lote") == pasta_lote, "o registro de entrega de cada artigo aponta o lote")
rec = L.por_pasta(pasta_lote)
ok(rec and rec.get("depositado_em") and rec.get("depositado_por") == "Administrador", "o lote fica marcado como depositado")
lotes_json = json.load(io.open(os.path.join(tmp, "lotes.json"), encoding="utf-8"))
ok(lotes_json.get("rdp|17|3", {}).get("proximo") == 2, f"a sequência avança uma vez, não uma por artigo: {lotes_json.get('rdp|17|3', {}).get('proximo')}")
ok("erro" in adm.post(f"/admin/lotes/{pasta_lote}/desfazer").headers["location"], "lote depositado não se desfaz")
ok("depositado" in adm.get("/admin/lotes").text, "a lista de lotes mostra a situação")
r = adm.post(f"/admin/lotes/{pasta_lote}/entrega", data={"correcao": "1"})
ok(os.path.exists(os.path.join(ftproot, "Correcao", pasta_lote + ".zip")), "correção do lote vai para a pasta Correcao")

# ---------------------------------------------------------------- 6. o segundo lote do mesmo número pega o 02
doc4, v4 = envia_e_completa("e92019")
r = adm.post("/admin/lotes", data={"doc": [doc4]})
ok("/admin/lotes/2179-8966-rdp-17-03-0226" in r.headers["location"], f"o lote seguinte do mesmo volume/número é o 02: {r.headers.get('location', '')[:60]}")

print("\nFALHAS:", len(falhas))
for f in falhas:
    print("  -", f)
shutil.rmtree(tmp, ignore_errors=True)
shutil.rmtree(ftproot, ignore_errors=True)
sys.exit(1 if falhas else 0)
