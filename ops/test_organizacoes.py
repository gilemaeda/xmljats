"""Organizações: contas agrupadas por editora/instituição, documentos e revistas compartilhados entre membros,
isolamento de quem está fora, convite, conta e administração."""
import io
import json
import os
import shutil
import sys
if hasattr(sys.stdout, "reconfigure"):  # console cp1252 do Windows nao imprime todo Unicode e derrubava o teste
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import tempfile
import urllib.parse

tmp = tempfile.mkdtemp(prefix="xmljats-org-")
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
import novidades as N  # noqa: E402

falhas = []


def ok(cond, msg):
    print(("ok   " if cond else "FALHA"), msg)
    if not cond:
        falhas.append(msg)


ORGS = M.ORGS
PDF = os.path.join(RAIZ, "modelos", "Direito e Praxis.pdf")
_ip = [0]


def cliente(nome, email, **extra):
    _ip[0] += 1
    c = TestClient(app, follow_redirects=False)
    r = c.post("/registrar", data={"nome": nome, "email": email, "senha": "senha-forte-1", "senha2": "senha-forte-1", **extra},
               headers={"x-forwarded-for": f"10.4.4.{_ip[0]}"})
    if r.status_code == 303:
        c.cookies.set("xmljats_sessao", r.cookies["xmljats_sessao"])
    return c, r


def uid(email):
    return next(u["id"] for u in M.CONTAS.lista() if u["email"] == email)


def envia(c, revista="rdp"):
    with open(PDF, "rb") as f:
        r = c.post("/validar", files={"arquivo": ("a.pdf", f, "application/pdf")}, data={"revista": revista, "sps": "1.10"})
    return r, (r.headers.get("location", "").rsplit("/", 1)[-1] if r.status_code == 303 else None)


# ---------------------------------------------------------------- 1. o módulo
o = ORGS.cria("Editora X", por="teste")
ok(len(o["convite"]) == 8 and o["convite"].isupper(), f"organização nasce com código de convite: {o['convite']}")
ok(ORGS.por_convite(o["convite"].lower())["id"] == o["id"] and ORGS.por_convite(" " + o["convite"][:4] + "-" + o["convite"][4:] + " ")["id"] == o["id"],
   "o código é aceito em minúsculas, com espaços ou hífen")
for ruim, motivo in (("editora x", "nome repetido, ignorando maiúsculas"), ("ab", "nome curto")):
    try:
        ORGS.cria(ruim)
        ok(False, f"{motivo} deveria ser recusado")
    except ValueError:
        ok(True, f"{motivo} é recusado")
ok(ORGS.renomeia(o["id"], "Editora X Ltda")["nome"] == "Editora X Ltda", "renomear funciona")
antigo = o["convite"]
novo = ORGS.novo_convite(o["id"])["convite"]
ok(novo != antigo and ORGS.por_convite(antigo) is None and ORGS.por_convite(novo)["id"] == o["id"], "novo código invalida o antigo")
convite = novo

# ---------------------------------------------------------------- 2. cadastro com convite, com organização nova e sem nada
a, _ = cliente("Ana", "ana@exemplo.org", convite=convite)
a2, _ = cliente("Aldo", "aldo@exemplo.org", convite=convite)
b, _ = cliente("Bia", "bia@exemplo.org", organizacao_nova="Revista Y")
c_, _ = cliente("Caio", "caio@exemplo.org")
ok(M.CONTAS.por_id(uid("ana@exemplo.org")).get("organizacao") == o["id"] and M.CONTAS.por_id(uid("aldo@exemplo.org")).get("organizacao") == o["id"],
   "quem se cadastra com o convite entra na organização")
org_b = M.CONTAS.por_id(uid("bia@exemplo.org")).get("organizacao")
ok(org_b and ORGS.por_id(org_b)["nome"] == "Revista Y" and org_b != o["id"], "quem cria uma organização no cadastro fica nela")
ok(M.CONTAS.por_id(uid("caio@exemplo.org")).get("organizacao") is None, "sem convite nem nome, a conta fica sem organização")
_, r = cliente("Dora", "dora@exemplo.org", convite="ZZZZZZZZ")
ok(r.status_code == 400 and not any(u["email"] == "dora@exemplo.org" for u in M.CONTAS.lista()), "convite errado recusa o cadastro sem criar a conta")
_, r = cliente("Eva", "eva@exemplo.org", organizacao_nova="editora x ltda")
ok(r.status_code == 400 and not any(u["email"] == "eva@exemplo.org" for u in M.CONTAS.lista()), "nome de organização já usado recusa o cadastro")

# ---------------------------------------------------------------- 3. documentos: colegas veem, os outros não
r, doc_a = envia(a)
ok(r.status_code == 303 and doc_a, "Ana envia um artigo")
cfg = json.load(io.open(os.path.join(tmp, "docs", doc_a, "config.json"), encoding="utf-8"))
ok(cfg.get("organizacao") == o["id"], "o documento nasce na organização de quem enviou")
ok(a2.get(f"/doc/{doc_a}").status_code == 200, "o colega da mesma organização abre o documento")
ok(a2.get(f"/doc/{doc_a}/editar").status_code == 200, "e pode revisar")
ok(b.get(f"/doc/{doc_a}").status_code == 403 and c_.get(f"/doc/{doc_a}").status_code == 403, "quem está em outra organização, ou em nenhuma, não vê")
pa2 = a2.get("/painel").text
ok(doc_a in pa2 and "enviado por Ana" in pa2, "a lista do colega mostra o documento e quem enviou")
r, doc_c = envia(c_)
ok(a.get(f"/doc/{doc_c}").status_code == 403, "documento de quem não tem organização é só dele")

# Ana passa a administrar a Editora X: cadastrar revista na organização é do admin dela; Aldo é só membro
M.ORGS.define_admin(o["id"], uid("ana@exemplo.org"), True)
ok(uid("ana@exemplo.org") in ORGS.por_id(o["id"])["admins"] and uid("aldo@exemplo.org") in ORGS.por_id(o["id"])["membros"]
   and uid("aldo@exemplo.org") not in ORGS.por_id(o["id"])["admins"], "quem entra pelo convite é membro; o admin da organização é definido à parte")

# ---------------------------------------------------------------- 4. revistas: da organização, pessoais e de catálogo
form_rev = {"acronimo": "edx", "titulo": "Revista da Editora X", "abrev": "Rev. Ed. X", "issn_epub": "1413-9936", "editora": "Editora X",
            "licenca_url": "https://creativecommons.org/licenses/by/4.0/", "modo_publicacao": "continua"}
ok(a.post("/revistas/nova", data=form_rev).status_code == 303, "Ana cadastra uma revista")
rev = next(x for x in M.carrega_revistas() if x["acronimo"] == "edx")
ok(rev.get("organizacao") == o["id"], "a revista fica da organização")
ok(M.acesso.papel_em(uid("aldo@exemplo.org"), "edx") == "secretaria_editorial" and M.acesso.papel_em(uid("ana@exemplo.org"), "edx") == "secretaria_editorial",
   "os membros ganham secretaria editorial na revista nova")
ok(a2.post("/revistas/nova", data=dict(form_rev, acronimo="ald", titulo="Revista do Aldo", issn_epub="2222-2227")).status_code == 403
   and a2.get("/revistas/nova").status_code == 403, "membro que não administra a organização não cadastra revista")
ok("edx" in a2.get("/revistas").text and 'value="edx"' in a2.get("/").text, "o colega vê a revista na lista e no envio")
ok("edx" not in b.get("/revistas").text and 'value="edx"' not in b.get("/").text and "edx" not in c_.get("/revistas").text,
   "quem está fora não vê a revista da organização")
ok("rdp" in b.get("/revistas").text and 'value="rdp"' in c_.get("/").text, "as revistas públicas continuam para todos")
ok(c_.post("/revistas/nova", data=dict(form_rev, acronimo="cpv", titulo="Revista do Caio", issn_epub="2179-8966")).status_code == 303, "Caio cadastra a dele")
rev_c = next(x for x in M.carrega_revistas() if x["acronimo"] == "cpv")
org_c = ORGS.por_id(rev_c.get("organizacao"))
ok(org_c and org_c["nome"] == "Organização de Caio" and uid("caio@exemplo.org") in org_c["admins"] and "dono" not in rev_c
   and "cpv" in c_.get("/revistas").text and "cpv" not in a.get("/revistas").text,
   "revista de quem não tem organização vira de uma organização pessoal dele (que ele administra)")
ok(M.CONTAS.por_id(uid("caio@exemplo.org")).get("organizacao") == org_c["id"] and "Organização de Caio" in c_.get("/conta").text,
   "a organização pessoal aparece em Minha conta")
r, _ = envia(b, revista="edx")
ok(r.status_code == 400, "enviar para uma revista fora do alcance é recusado")
adm = TestClient(app, follow_redirects=False)
ra = adm.post("/entrar", data={"email": "admin", "senha": "senha-de-teste-123", "proximo": "/"}, headers={"x-forwarded-for": "10.4.5.1"})
adm.cookies.set("xmljats_sessao", ra.cookies["xmljats_sessao"])
pr = adm.get("/revistas").text
ok("edx" in pr and "Editora X Ltda" in pr and "Organização de Caio" in pr, "o administrador vê todas, com a marca de quem é cada uma")
form_edit = {k: v for k, v in rev.items() if isinstance(v, str)}
form_edit["na_scielo"] = "nao"
ok(adm.post("/revistas/edx", data=form_edit).status_code == 303
   and next(x for x in M.carrega_revistas() if x["acronimo"] == "edx").get("organizacao") == o["id"], "editar a revista não muda de quem ela é")

# ---------------------------------------------------------------- 5. administrador vincula uma conta; o que era dela antes continua só dela
r = adm.post(f"/usuarios/{uid('caio@exemplo.org')}/organizacao", data={"organizacao": o["id"]})
ok(r.status_code == 303 and M.CONTAS.por_id(uid("caio@exemplo.org")).get("organizacao") == o["id"], "administrador vincula Caio à Editora X")
ok(c_.get(f"/doc/{doc_a}").status_code == 200, "Caio passa a ver os documentos da organização")
ok(uid("caio@exemplo.org") in ORGS.por_id(o["id"])["membros"] and M.acesso.papel_em(uid("caio@exemplo.org"), "edx") == "secretaria_editorial",
   "vinculado pelo administrador, Caio vira membro e secretaria editorial nas revistas dela")
ok("cpv" in c_.get("/revistas").text and uid("caio@exemplo.org") in ORGS.por_id(org_c["id"])["admins"],
   "e continua administrando a organização pessoal dele, com a revista dela")
ok(a.get(f"/doc/{doc_c}").status_code == 403, "o documento que Caio enviou antes continua só dele")
r, doc_c2 = envia(c_)
ok(a.get(f"/doc/{doc_c2}").status_code == 200, "o que Caio envia depois é da organização")
ok(adm.post(f"/usuarios/{uid('caio@exemplo.org')}/organizacao", data={"organizacao": "inexistente"}).headers["location"].find("erro") > 0,
   "vincular a organização inexistente é recusado")
ok('name="organizacao"' in adm.get("/usuarios").text and "Editora X Ltda" in adm.get("/usuarios").text, "Usuários tem o seletor de organização")

# ---------------------------------------------------------------- 6. Minha conta: entrar por código ou criar
f_, _ = cliente("Fabi", "fabi@exemplo.org")
ok("Código de convite" in f_.get("/conta").text, "sem organização, a conta oferece entrar por código ou criar")
ok("erro" in f_.post("/conta/organizacao", data={"convite": "NADA1234"}).headers["location"], "código errado é recusado")
ok("mensagem" in f_.post("/conta/organizacao", data={"convite": convite}).headers["location"]
   and M.CONTAS.por_id(uid("fabi@exemplo.org")).get("organizacao") == o["id"], "código certo coloca a pessoa na organização")
ok(convite in f_.get("/conta").text and "Editora X Ltda" in f_.get("/conta").text, "a conta mostra a organização e o código para convidar colegas")
ok("mensagem" in f_.post("/conta/organizacao", data={"nome": "Outra"}).headers["location"]
   and len(M.acesso.organizacoes_de(uid("fabi@exemplo.org"))) == 2 and M.CONTAS.por_id(uid("fabi@exemplo.org")).get("organizacao") == o["id"],
   "quem já está numa organização pode criar (ou entrar em) outra: os papéis são por revista, e a principal continua a primeira")
ok("erro" in f_.post("/conta/organizacao", data={"convite": convite}).headers["location"], "entrar de novo na mesma organização é recusado")
g, _ = cliente("Gil", "gil@exemplo.org")
ok("mensagem" in g.post("/conta/organizacao", data={"nome": "Instituto G"}).headers["location"]
   and ORGS.por_id(M.CONTAS.por_id(uid("gil@exemplo.org")).get("organizacao"))["nome"] == "Instituto G", "criar organização pela conta")
ok("erro" in g.post("/conta/organizacao", data={}).headers["location"] or True, "pedido vazio não quebra")

# ---------------------------------------------------------------- 7. administração de organizações
pg = adm.get("/admin/organizacoes").text
ok("Editora X Ltda" in pg and "Revista Y" in pg and "Instituto G" in pg, "a página lista as organizações")
ok(adm.post("/admin/organizacoes", data={"nome": "Nova Org"}).status_code == 303 and any(x["nome"] == "Nova Org" for x in ORGS.lista()), "criar pela administração")
nova = next(x for x in ORGS.lista() if x["nome"] == "Nova Org")
ok("mensagem" in adm.post(f"/admin/organizacoes/{nova['id']}/nome", data={"nome": "Nova Org 2"}).headers["location"]
   and ORGS.por_id(nova["id"])["nome"] == "Nova Org 2", "renomear pela administração")
ok("mensagem" in adm.post(f"/admin/organizacoes/{nova['id']}/convite").headers["location"] and ORGS.por_id(nova["id"])["convite"] != nova["convite"],
   "novo código pela administração")
ok("erro" in adm.post(f"/admin/organizacoes/{o['id']}/remover").headers["location"] and ORGS.por_id(o["id"]), "organização com membros não é removida")
ok("mensagem" in adm.post(f"/admin/organizacoes/{nova['id']}/remover").headers["location"] and ORGS.por_id(nova["id"]) is None, "organização vazia é removida")
ok("membros" in pg.lower() and "Documentos" in pg, "a página mostra membros e documentos por organização")

# ---------------------------------------------------------------- 8. quem não é administrador não administra
ok(a.get("/admin/organizacoes").status_code == 403 and a.post("/admin/organizacoes", data={"nome": "X"}).status_code == 403
   and a.post(f"/usuarios/{uid('bia@exemplo.org')}/organizacao", data={"organizacao": o["id"]}).status_code == 403,
   "cliente não cria, nem vincula, nem lista organizações pela administração")
M.CONTAS.cria("op@exemplo.org", "Op", "senha-forte-1", "operador")
op = TestClient(app, follow_redirects=False)
ro = op.post("/entrar", data={"email": "op@exemplo.org", "senha": "senha-forte-1", "proximo": "/"}, headers={"x-forwarded-for": "10.4.5.2"})
op.cookies.set("xmljats_sessao", ro.cookies["xmljats_sessao"])
ok(op.get(f"/doc/{doc_a}").status_code == 200 and op.get(f"/doc/{doc_c}").status_code == 200 and "edx" in op.get("/revistas").text,
   "operador continua vendo tudo")
ok("Revista da Editora X" in adm.get("/admin/documentos").text or "Editora X Ltda" in adm.get("/admin/documentos").text,
   "a lista do administrador mostra a organização do documento")

# ---------------------------------------------------------------- 9. ISSN de revista de outra organização; visibilidade; filtros; reexibir novidades
j = b.get("/revistas/consulta?numero=1413-9936").json()
ok(j.get("cadastrada") and j.get("oculta") and "outra organização" in (j.get("mensagem") or ""),
   "consulta de ISSN de revista de outra organização avisa em vez de cadastrar de novo")
r = b.post("/revistas/importar", data={"numero": "1413-9936", "voltar": "/"})
ok(r.status_code == 303 and "outra organiza" in urllib.parse.unquote(r.headers["location"]), "importar pelo ISSN também avisa")
ok(next(x for x in M.carrega_revistas() if x["acronimo"] == "edx").get("organizacao") == o["id"], "e a revista continua da organização de Ana")
form_pub = dict(form_edit, visibilidade="publica")
ok(adm.post("/revistas/edx", data=form_pub).status_code == 303 and not next(x for x in M.carrega_revistas() if x["acronimo"] == "edx").get("organizacao"),
   "'Quem vê esta revista' = pública tira a revista da organização")
ok("edx" in b.get("/revistas").text, "agora Bia vê a revista")
form_org = dict(form_edit, visibilidade=f"org:{org_b}")
ok(adm.post("/revistas/edx", data=form_org).status_code == 303 and next(x for x in M.carrega_revistas() if x["acronimo"] == "edx").get("organizacao") == org_b,
   "e pode mudar a revista de organização")
ok("edx" not in a.get("/revistas").text and "edx" in b.get("/revistas").text, "a revista passou para a organização de Bia")
ok(M.acesso.papel_em(uid("ana@exemplo.org"), "edx") is None and M.acesso.papel_em(uid("bia@exemplo.org"), "edx") == "secretaria_editorial",
   "mudar a organização da revista move os papéis: Ana perde o dela, Bia (membro da nova) ganha secretaria")
ok('name="visibilidade"' in adm.get("/revistas/edx").text and 'name="visibilidade"' not in adm.get("/revistas/nova").text,
   "o seletor 'Quem vê esta revista' só aparece ao editar")
pd = adm.get(f"/admin/documentos?organizacao={o['id']}").text
ok(doc_a in pd and doc_c not in pd, "filtro por organização na lista do administrador")
ok('name="organizacao"' in pd and "Editora X Ltda" in pd, "o filtro e o nome da organização aparecem na lista")
ok("<th>Organização</th>" in adm.get("/usuarios").text, "Usuários tem a coluna Organização")
M.CONTAS.marca_novidades(uid("ana@exemplo.org"), N.ATUAL)
ok('id="novidades-modal"' not in a.get("/painel").text, "Ana não tem novidade pendente")
ok(adm.post(f"/usuarios/{uid('ana@exemplo.org')}/novidades").status_code == 303 and 'id="novidades-modal"' in a.get("/painel").text,
   "'Reexibir novidades' faz a janela voltar para a conta")
po = adm.get("/admin/organizacoes").text
ok("Membros:" in po and "Ana" in po and "Aldo" in po, "a página Organizações lista os membros")
ok("[hidden]{display:none!important}" in io.open(os.path.join(RAIZ, "app", "static", "style.css"), encoding="utf-8").read(),
   "CSS: [hidden] vence o display dos campos (caixa do ISSN some de verdade)")
aj_a = a.get("/ajuda").text
aj_adm = adm.get("/ajuda").text
ok("quem vê o quê" in aj_a and "Para o administrador" not in aj_a and "Para o administrador" in aj_adm,
   "Como funciona explica organizações; a parte do administrador só aparece para ele")

# ---------------------------------------------------------------- 10. nada do painel administrativo aparece em página de cliente
import re as _re
PALAVRAS_ADMIN = ("configurações", "correio", "painel administrativo", "usuários", "/admin", "administrador")
paginas = ["/", "/painel", "/conta", "/revistas", "/revistas/nova", "/ajuda", "/novidades", f"/doc/{doc_a}", f"/doc/{doc_a}/editar", f"/doc/{doc_a}/entrega"]
for pg_ in paginas:
    html = a.get(pg_).text
    texto = _re.sub(r"<script.*?</script>", " ", html, flags=_re.S)
    texto = _re.sub(r"<[^>]+>", " ", texto).lower()
    achadas = [w for w in PALAVRAS_ADMIN if w in texto]
    ok(not achadas, f"página de cliente {pg_} sem vocabulário administrativo {achadas}")

print("\nFALHAS:", len(falhas))
for f in falhas:
    print("  -", f)
shutil.rmtree(tmp, ignore_errors=True)
sys.exit(1 if falhas else 0)
