"""Meus documentos: data da ultima abertura e ordenacao da lista."""
import io
import json
import os
import re
import shutil
import sys
if hasattr(sys.stdout, "reconfigure"):  # console cp1252 do Windows nao imprime todo Unicode e derrubava o teste
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import tempfile
import time

tmp = tempfile.mkdtemp(prefix="xmljats-lista-")
os.environ["XMLJATS_DATA"] = tmp
os.environ["APP_SENHA"] = "senha-de-teste-123"
RAIZ = r"C:\Users\gilej\PROJETOS\XML"
sys.path.insert(0, RAIZ)
sys.path.insert(0, os.path.join(RAIZ, "app"))
from fastapi.testclient import TestClient  # noqa: E402
import app.main as M  # noqa: E402
from app.main import app  # noqa: E402

falhas = []


def ok(cond, msg):
    print(("ok   " if cond else "FALHA"), msg)
    if not cond:
        falhas.append(msg)


c = TestClient(app, follow_redirects=False)
reg = c.post("/registrar", data={"nome": "Lista", "email": "lista@exemplo.org", "senha": "senha-forte-1", "senha2": "senha-forte-1"})
c.cookies.set("xmljats_sessao", reg.cookies["xmljats_sessao"])

docs = []
for nome, revista in (("Direito e Praxis.pdf", "rdp"), ("1227_VF+-+Simioni (3).pdf", "anamps"),
                      ("RBDPP_2026_v12n2_1498.pdf", "rbdpp")):
    caminho = os.path.join(RAIZ, "modelos", nome)
    if not os.path.exists(caminho):
        continue
    with open(caminho, "rb") as f:
        r = c.post("/validar", files={"arquivo": (nome, f, "application/pdf")}, data={"revista": revista, "sps": "1.9"})
    docs.append(r.headers["location"].rsplit("/", 1)[-1])
    time.sleep(1.1)
ok(len(docs) == 3, f"{len(docs)} documentos enviados para a prova (o terceiro fica sem ser aberto)")

# ---------------------------------------------------------------- 1. nunca aberto
pag = c.get("/painel").text
ok("Aberto" in pag and "nunca aberto" in pag, "a coluna 'Aberto' aparece e diz quando nunca foi aberto")
for d in docs:
    cfg = json.load(io.open(os.path.join(tmp, "docs", d, "config.json"), encoding="utf-8"))
    ok(not cfg.get("aberto_em"), f"documento recem-enviado ainda nao consta como aberto ({d[-6:]})")

# ---------------------------------------------------------------- 2. abrir o resultado registra
c.get(f"/doc/{docs[0]}")
cfg = json.load(io.open(os.path.join(tmp, "docs", docs[0], "config.json"), encoding="utf-8"))
ok(cfg.get("aberto_em") and cfg.get("aberto_por") == "Lista", f"abrir o resultado registra quem e quando: {cfg.get('aberto_em')}")
ok(cfg.get("aberturas") == 1, f"conta as aberturas: {cfg.get('aberturas')}")
c.get(f"/doc/{docs[0]}")
cfg2 = json.load(io.open(os.path.join(tmp, "docs", docs[0], "config.json"), encoding="utf-8"))
ok(cfg2.get("aberturas") == 1, "clique repetido no mesmo minuto nao reescreve o arquivo a toa")

# abrir a tela de revisar tambem conta
time.sleep(1)
c.get(f"/doc/{docs[1]}/editar")
cfg3 = json.load(io.open(os.path.join(tmp, "docs", docs[1], "config.json"), encoding="utf-8"))
ok(cfg3.get("aberto_em"), "abrir 'revisar e editar' tambem registra a abertura")

pag = c.get("/painel").text
ok(pag.count("nunca aberto") == len(docs) - 2,
   f"so o documento que ninguem abriu segue marcado como nunca aberto ({pag.count('nunca aberto')})")

# ---------------------------------------------------------------- 3. ordenacao
ok('name="ordem"' in pag and "Aberto mais recente" in pag, "o seletor de ordenacao esta na tela")
rotulos = [r for _c, r, _f, _rv in M.ORDENS]
for r in rotulos:
    ok(r in pag, f"opcao de ordem na tela: {r}")


def ids_na_ordem(query):
    txt = c.get("/painel" + query).text
    corpo = txt.split("<tbody>")[1].split("</tbody>")[0]
    return re.findall(r'href="/doc/([0-9]{8}-[0-9]{6}-[0-9a-f]{6})"', corpo)[::2] or \
        re.findall(r'/doc/([0-9]{8}-[0-9]{6}-[0-9a-f]{6})', corpo)


# o ultimo aberto foi docs[1]; por 'aberto' ele tem de vir na frente de docs[0]
por_aberto = ids_na_ordem("?ordem=aberto")
ok(por_aberto and por_aberto[0] == docs[1],
   f"ordenar por 'aberto mais recente' poe o ultimo aberto no topo ({por_aberto[0][-6:] if por_aberto else '-'} vs {docs[1][-6:]})")
nunca = [d for d in docs if d not in (docs[0], docs[1])]
if nunca:
    ok(por_aberto.index(nunca[0]) > por_aberto.index(docs[1]), "documento nunca aberto vai para o fim")

por_criado = ids_na_ordem("?ordem=criado")
ok(por_criado and por_criado[0] == docs[-1], "ordenar por 'enviado mais recente' poe o ultimo envio no topo")
por_antigo = ids_na_ordem("?ordem=antigo")
ok(por_antigo and por_antigo[0] == docs[0], "ordenar por 'enviado mais antigo' inverte")
ok(por_antigo == por_criado[::-1], "as duas ordens de envio sao exatamente inversas")

titulos = []
for d in ids_na_ordem("?ordem=titulo"):
    v = json.load(io.open(os.path.join(tmp, "docs", d, "validacao.json"), encoding="utf-8"))
    titulos.append((v.get("titulo") or v.get("arquivo_original") or "").lower())
ok(titulos == sorted(titulos), f"ordem por titulo fica em A-Z: {[t[:22] for t in titulos]}")

bloq = []
for d in ids_na_ordem("?ordem=situacao"):
    v = json.load(io.open(os.path.join(tmp, "docs", d, "validacao.json"), encoding="utf-8"))
    bloq.append(len(v.get("bloqueantes") or []))
ok(bloq == sorted(bloq, reverse=True), f"ordem por situacao poe os mais bloqueados primeiro: {bloq}")

ok(ids_na_ordem("?ordem=inventada") == ids_na_ordem(""), "ordem desconhecida cai no padrao, sem erro")
ok('value="aberto" selected' in c.get("/painel?ordem=aberto").text, "a ordem escolhida fica marcada no seletor")

# a ordem se mantem junto com o filtro
pag_f = c.get("/painel?ordem=aberto&revista=rdp").text
ok('value="aberto" selected' in pag_f and 'value="rdp" selected' in pag_f, "ordem e filtro convivem")
ok("ordem=aberto" in pag_f, "a ordem volta no link de manter estado")

# ---------------------------------------------------------------- 4. lista do administrador
adm = TestClient(app, follow_redirects=False)
ra = adm.post("/entrar", data={"email": "admin", "senha": "senha-de-teste-123", "proximo": "/"})
adm.cookies.set("xmljats_sessao", ra.cookies["xmljats_sessao"])
pa = adm.get("/admin/documentos?ordem=aberto").text
ok("Aberto" in pa and 'name="ordem"' in pa, "a lista do administrador tem coluna e ordenacao")
ok("Lista" in pa, "e mostra quem abriu por ultimo")

# ---------------------------------------------------------------- 5. isolamento
c2 = TestClient(app, follow_redirects=False)
r2 = c2.post("/registrar", data={"nome": "Outra", "email": "outra@exemplo.org", "senha": "senha-forte-1", "senha2": "senha-forte-1"})
c2.cookies.set("xmljats_sessao", r2.cookies["xmljats_sessao"])
ok(c2.get(f"/doc/{docs[0]}").status_code == 403, "conta de outro dono nao abre o documento")
cfg4 = json.load(io.open(os.path.join(tmp, "docs", docs[0], "config.json"), encoding="utf-8"))
ok(cfg4.get("aberto_por") == "Lista", "e a tentativa recusada nao altera quem abriu por ultimo")

print("\nFALHAS:", len(falhas))
for f in falhas:
    print("  -", f)
shutil.rmtree(tmp, ignore_errors=True)
sys.exit(1 if falhas else 0)
