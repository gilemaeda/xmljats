"""Consulta de revista pelo ISSN: modulo, rota JSON, cadastro automatico e campo no validador."""
import io
import json
import os
import shutil
import sys
if hasattr(sys.stdout, "reconfigure"):  # console cp1252 do Windows nao imprime todo Unicode e derrubava o teste
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import tempfile

tmp = tempfile.mkdtemp(prefix="xmljats-issn-")
os.environ["XMLJATS_DATA"] = tmp
os.environ["APP_SENHA"] = "senha-de-teste-123"
sys.path.insert(0, r"C:\Users\gilej\PROJETOS\XML")
sys.path.insert(0, r"C:\Users\gilej\PROJETOS\XML\app")
from fastapi.testclient import TestClient  # noqa: E402
import app.main as M  # noqa: E402
from app.main import app  # noqa: E402
import issn as I  # noqa: E402

c = TestClient(app, follow_redirects=False)
falhas = []


def ok(cond, msg):
    print(("ok   " if cond else "FALHA"), msg)
    if not cond:
        falhas.append(msg)


def entra(cli, email, senha):
    r = cli.post("/entrar", data={"email": email, "senha": senha, "proximo": "/"})
    if r.status_code == 303 and "xmljats_sessao" in r.cookies:
        cli.cookies.set("xmljats_sessao", r.cookies["xmljats_sessao"])
    return r


entra(c, "admin", "senha-de-teste-123")

# ---- digito verificador e normalizacao
ok(I.valido("2179-8966") and I.valido("0034-8910") and I.valido("2446-8088"), "ISSN valido reconhecido")
ok(not I.valido("2179-8967") and not I.valido("1234-5678"), "digito verificador errado e recusado")
ok(I.normaliza(" 21798966 ") == "2179-8966" and I.normaliza("2179 8966") == "2179-8966", "normaliza o formato")

# ---- consulta em cascata (rede)
r = I.consulta("2179-8966")
ok(r["ok"], "consulta acha a Revista Direito e Praxis")
ok(r["dados"].get("acronimo") == "rdp", "acronimo vem da SciELO: " + str(r["dados"].get("acronimo")))
ok(r["dados"].get("abrev", "").startswith("Rev. Direito"), "titulo abreviado vem do Portal do ISSN: " + str(r["dados"].get("abrev")))
ok("creativecommons.org" in (r["dados"].get("licenca") or ""), "licenca vem do DOAJ: " + str(r["dados"].get("licenca")))
ok(len([f for f in r["fontes"] if f["ok"]]) >= 3, f"pelo menos 3 fontes responderam ({len([f for f in r['fontes'] if f['ok']])})")
ok(all(campo in r["origem"] for campo in ("titulo", "abrev", "acronimo")), "cada campo diz de onde veio")

r2 = I.consulta("1518-8787")  # SciELO indexa a RSP pelo ISSN impresso
ok((r2["dados"].get("acronimo") == "rsp"), "ISSN irmao: a RSP e achada na SciELO pelo 0034-8910")

r3 = I.consulta("2179-8967")
ok(not r3["ok"] and "verificador" in r3["mensagem"], "ISSN com digito errado nao vai para a rede")

# ---- rota JSON usada pelo campo do validador
j = c.get("/revistas/consulta?numero=2317-6172").json()
ok(j["ok"] and not j["cadastrada"], "rota JSON responde para ISSN fora do cadastro")
ok(j["dados"].get("titulo"), "rota JSON traz o titulo")
ok(any(f["fonte"].startswith("Portal do ISSN") for f in j["fontes"]), "rota JSON lista as fontes consultadas")

j = c.get("/revistas/consulta?numero=0000-0000").json()
ok(not j["ok"] and "Nenhuma" in j["mensagem"], "ISSN sem registro devolve mensagem clara")

# ---- cadastro automatico pelo ISSN
antes = len(M.carrega_revistas())
r = c.post("/revistas/importar", data={"numero": "2317-6172", "voltar": "/revistas"})
ok(r.status_code == 303 and "mensagem" in r.headers["location"], "importar por ISSN redireciona com mensagem")
lista = M.carrega_revistas()
nova = next((x for x in lista if (x.get("issn_epub") or "") == "2317-6172"), None)
ok(nova is not None, "revista cadastrada pelo ISSN")
if nova:
    ok(nova["titulo"] and nova["abrev"] and nova["editora"] and nova["issn_epub"] == "2317-6172",
       f"cadastro completo: {nova['titulo']} / {nova['abrev']} / {nova['editora']}")
    ok("Importado pelo ISSN" in (nova.get("_fonte") or "") and "Portal do ISSN" in (nova.get("_fonte") or ""),
       "observacoes registram a origem de cada campo")
    ok(nova["licenca_url"].startswith("https://creativecommons.org/licenses/"), "licenca gravada como URL CC")

# ISSN ja cadastrado nao duplica
r = c.post("/revistas/importar", data={"numero": "2317-6172", "voltar": "/revistas"})
ok(len(M.carrega_revistas()) == len(lista), "ISSN ja cadastrado nao cria duplicata")
j = c.get("/revistas/consulta?numero=2179-8966").json()
ok(j["cadastrada"] and j["acronimo"] == "rdp", "rota JSON reconhece revista ja cadastrada")

# ---- telas
pag = c.get("/revistas").text
ok("Cadastrar pelo ISSN" in pag and "CBISSN" in pag, "pagina Revistas explica a origem dos dados e importa por ISSN")
ok("cbissn.ibict.br" in pag, "pagina Revistas aponta o CBISSN para pedir ISSN novo")
pag = c.get("/revistas/nova?issn=2317-6172").text
ok("Direito GV" in pag, "formulario de nova revista vem preenchido pela busca")
ok("issn-fontes" in pag, "formulario mostra o que cada base respondeu")

# ---- campo no validador (conta cliente, que e quem ve o validador)
c2 = TestClient(app, follow_redirects=False)
r = c2.post("/registrar", data={"nome": "Cliente ISSN", "email": "issn@exemplo.org", "senha": "senha-forte-1", "senha2": "senha-forte-1"})
c2.cookies.set("xmljats_sessao", r.cookies["xmljats_sessao"])
pag = c2.get("/").text
ok('id="issn-box"' in pag and 'id="issn-numero"' in pag, "validador tem o campo de ISSN")
ok("Detectar pelo ISSN" in pag, "opcao 'Detectar pelo ISSN' na lista de revistas")
ok("/revistas/consulta?numero=" in pag, "o campo consulta a rota das bases")
pag = c2.get("/?revista=rdp&mensagem=Revista+cadastrada").text
ok('value="rdp" selected' in pag, "voltando do cadastro, a revista ja vem selecionada")

# envio com ISSN e sem revista escolhida: o documento sai com a revista resolvida
with open(r"C:\Users\gilej\PROJETOS\XML\modelos\Direito e Praxis.pdf", "rb") as f:
    r = c2.post("/validar", files={"arquivo": ("a.pdf", f, "application/pdf")}, data={"revista": "", "sps": "1.9", "issn": "2179-8966"})
ok(r.status_code == 303, "envio com ISSN aceito")
doc_id = r.headers["location"].rsplit("/", 1)[-1]
cfg = json.load(io.open(os.path.join(tmp, "docs", doc_id, "config.json"), encoding="utf-8"))
ok(cfg.get("revista") == "rdp", f"documento ficou com a revista resolvida pelo ISSN (revista={cfg.get('revista')})")
ok(cfg.get("issn_informado") == "2179-8966", "o ISSN informado fica registrado no documento")

print("\nFALHAS:", len(falhas))
for f in falhas:
    print("  -", f)
shutil.rmtree(tmp, ignore_errors=True)
sys.exit(1 if falhas else 0)
