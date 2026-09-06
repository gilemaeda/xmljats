"""Acesso centralizado (etapa 2 do multi-tenant): papéis por revista, admins e membros da organização, matriz de
permissões (enviar, corrigir, aprovar, ver, cadastrar revista), isolamento entre organizações, uma pessoa com papéis
diferentes em duas organizações, aprovação do editor-chefe antes da entrega (artigo e lote), organização pessoal e a
migração dos dados de antes."""
import io
import json
import os
import shutil
import sys
if hasattr(sys.stdout, "reconfigure"):  # console cp1252 do Windows nao imprime todo Unicode e derrubava o teste
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import tempfile
import urllib.parse
from pathlib import Path

tmp = tempfile.mkdtemp(prefix="xmljats-acesso-")
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
import acesso as A  # noqa: E402
import lotes as L  # noqa: E402

falhas = []


def ok(cond, msg):
    print(("ok   " if cond else "FALHA"), msg)
    if not cond:
        falhas.append(msg)


ORGS, CONTAS = M.ORGS, M.CONTAS
DOCS = os.path.join(tmp, "docs")
PDF = os.path.join(RAIZ, "modelos", "Direito e Praxis.pdf")
_ip = [0]


def cliente(nome, email, **extra):
    _ip[0] += 1
    c = TestClient(app, follow_redirects=False)
    r = c.post("/registrar", data={"nome": nome, "email": email, "senha": "senha-forte-1", "senha2": "senha-forte-1", **extra},
               headers={"x-forwarded-for": f"10.7.7.{_ip[0]}"})
    assert r.status_code == 303, (nome, r.status_code, r.text[:200])
    c.cookies.set("xmljats_sessao", r.cookies["xmljats_sessao"])
    return c


def uid(email):
    return next(u["id"] for u in CONTAS.lista() if u["email"] == email)


def envia(c, revista):
    with open(PDF, "rb") as f:
        r = c.post("/validar", files={"arquivo": ("a.pdf", f, "application/pdf")}, data={"revista": revista, "sps": "1.10"})
    return r, (r.headers.get("location", "").rsplit("/", 1)[-1] if r.status_code == 303 else None)


def cfg_de(doc):
    return json.load(io.open(os.path.join(DOCS, doc, "config.json"), encoding="utf-8"))


def val_de(doc):
    return json.load(io.open(os.path.join(DOCS, doc, "validacao.json"), encoding="utf-8"))


def completa(c, doc, acr, elocation="e92016"):
    """Preenche o que falta (como ops/test_lotes.py) para o XML ficar pronto."""
    revista = next(x for x in M.carrega_revistas() if x["acronimo"] == acr)
    pasta = Path(DOCS) / doc
    modelo = M.modelo_efetivo(pasta)
    form = {"acao": "salvar", "revista": acr}
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
    form["volume"] = "17"
    return c.post(f"/doc/{doc}/editar", data=form)


def loc(r):
    return urllib.parse.unquote(r.headers.get("location", ""))


adm = TestClient(app, follow_redirects=False)
ra = adm.post("/entrar", data={"email": "admin", "senha": "senha-de-teste-123", "proximo": "/"}, headers={"x-forwarded-for": "10.7.8.1"})
adm.cookies.set("xmljats_sessao", ra.cookies["xmljats_sessao"])

# ---------------------------------------------------------------- 1. o módulo: papéis por revista
A.define_papel("u1", "rev1", "editor_chefe", "teste")
ok(A.papel_em("u1", "rev1") == "editor_chefe" and os.path.exists(os.path.join(tmp, "papeis.json")), "papel por revista gravado em papeis.json")
A.define_papel("u1", "rev1", "secretaria_editorial", "teste")
ok(A.papel_em("u1", "rev1") == "secretaria_editorial" and A.quem_tem("rev1") == ["u1"], "um papel por pessoa por revista: o novo substitui")
A.define_papel("u1", "rev2", "corpo_editorial", "teste")
ok(A.revistas_com_papel("u1") == {"rev1", "rev2"} and len(A.papeis_de("u1")) == 2, "a mesma pessoa tem papéis em revistas diferentes")
try:
    A.define_papel("u1", "rev1", "chefe")
    ok(False, "papel inválido deveria ser recusado")
except ValueError:
    ok(True, "papel inválido é recusado")
A.ao_renomear_revista("rev1", "rev1b")
ok(A.papel_em("u1", "rev1b") == "secretaria_editorial" and A.papel_em("u1", "rev1") is None, "renomear a revista leva os papéis junto")
A.define_papel("u1", "rev1b", None)
A.ao_remover_revista("rev2")
ok(not A.papeis_de("u1"), "remover o papel e remover a revista limpam papeis.json")
try:
    A.pode({"id": "x", "papel": "cliente"}, "voar")
    ok(False, "ação desconhecida deveria ser recusada")
except ValueError:
    ok(True, "ação desconhecida é recusada (a matriz é fechada)")

# ---------------------------------------------------------------- 2. o módulo: organização com admins e membros
o1 = ORGS.cria("Editora Módulo", por="teste")
ok(o1["tipo"] == "instituicao" and o1["admins"] == [] and o1["membros"] == [] and o1["pai"] is None and "plano" in o1,
   "organização nasce com tipo, admins, membros, pai e plano")
ORGS.adiciona_membro(o1["id"], "u1")
ORGS.adiciona_membro(o1["id"], "u1")
ORGS.define_admin(o1["id"], "u2", True)
o1 = ORGS.por_id(o1["id"])
ok(o1["membros"] == ["u1"] and o1["admins"] == ["u2"] and ORGS.pessoas(o1["id"]) == ["u1", "u2"], "membro não duplica; admin não precisa ser membro")
ORGS.remove_membro(o1["id"], "u2")
ORGS.remove_membro(o1["id"], "u1")
ok(ORGS.pessoas(o1["id"]) == [], "sair tira de membros e de admins")
try:
    ORGS.cria("Tipo Errado", tipo="loja")
    ok(False, "tipo inválido deveria ser recusado")
except ValueError:
    ok(True, "tipo de organização inválido é recusado")
ORGS.remove(o1["id"])

# ---------------------------------------------------------------- 3. pessoas, organizações e revistas por HTTP
rita = cliente("Rita", "rita@exemplo.org", organizacao_nova="Editora Multi")
ox = ORGS.por_id(CONTAS.por_id(uid("rita@exemplo.org"))["organizacao"])
ok(ox and ox["nome"] == "Editora Multi" and uid("rita@exemplo.org") in ox["admins"] and uid("rita@exemplo.org") in ox["membros"],
   "quem cria a organização no cadastro é admin e membro dela")
sol = cliente("Sol", "sol@exemplo.org", convite=ox["convite"])
ivo = cliente("Ivo", "ivo@exemplo.org", convite=ox["convite"])
eli = cliente("Eli", "eli@exemplo.org", convite=ox["convite"])
ox = ORGS.por_id(ox["id"])
ok(all(uid(e) in ox["membros"] and uid(e) not in ox["admins"] for e in ("sol@exemplo.org", "ivo@exemplo.org", "eli@exemplo.org")),
   "quem entra pelo convite é membro, não admin")
form_rev = {"acronimo": "edx", "titulo": "Revista da Editora Multi", "abrev": "Rev. Ed. Multi", "issn_epub": "1413-9936", "editora": "Editora Multi",
            "doi_prefixo": "10.99999/edx", "licenca_url": "https://creativecommons.org/licenses/by/4.0/", "modo_publicacao": "continua", "na_scielo": "nao"}
ok(rita.post("/revistas/nova", data=form_rev).status_code == 303, "o admin da organização cadastra uma revista nela")
ok(A.organizacao_da_revista("edx") == ox["id"], "a revista fica da organização")
ok(all(A.papel_em(uid(e), "edx") == "secretaria_editorial" for e in ("rita@exemplo.org", "sol@exemplo.org", "ivo@exemplo.org", "eli@exemplo.org")),
   "os membros nascem como secretaria editorial na revista nova")
ok(sol.post("/revistas/nova", data=dict(form_rev, acronimo="sx", issn_epub="2179-8966")).status_code == 403 and sol.get("/revistas/nova").status_code == 403,
   "membro que não administra a organização não cadastra revista")
A.define_papel(uid("ivo@exemplo.org"), "edx", "corpo_editorial", "teste")
A.define_papel(uid("eli@exemplo.org"), "edx", "editor_chefe", "teste")
yara = cliente("Yara", "yara@exemplo.org", organizacao_nova="Instituto Y")
oy = ORGS.por_id(CONTAS.por_id(uid("yara@exemplo.org"))["organizacao"])
ok(yara.post("/revistas/nova", data=dict(form_rev, acronimo="iny", titulo="Revista do Instituto Y", issn_epub="2179-8966",
                                          editora="Instituto Y", doi_prefixo="10.99999/iny")).status_code == 303, "Yara cadastra a revista do Instituto Y")
r = eli.post("/conta/organizacao", data={"convite": oy["convite"]})
ok("mensagem" in r.headers["location"] and uid("eli@exemplo.org") in ORGS.por_id(oy["id"])["membros"], "Eli entra também no Instituto Y pelo convite")
ok(A.papel_em(uid("eli@exemplo.org"), "iny") == "secretaria_editorial" and A.papel_em(uid("eli@exemplo.org"), "edx") == "editor_chefe",
   "a mesma pessoa é editor-chefe numa revista e secretaria em outra, de organizações diferentes")
ok(CONTAS.por_id(uid("eli@exemplo.org"))["organizacao"] == ox["id"], "a organização principal continua a primeira")
rv, home = eli.get("/revistas").text, eli.get("/").text
ok("edx" in rv and "iny" in rv and 'value="edx"' in home and 'value="iny"' in home, "Eli vê as duas revistas (lista e envio)")
ok("iny" not in sol.get("/revistas").text and "edx" not in yara.get("/revistas").text and 'value="edx"' not in yara.get("/").text,
   "cada organização só vê as revistas dela (e as de catálogo)")

# ---------------------------------------------------------------- 4. matriz: enviar
r, doc_sol = envia(sol, "edx")
ok(r.status_code == 303 and doc_sol and cfg_de(doc_sol)["organizacao"] == ox["id"], "secretaria envia; o documento nasce na organização da revista")
r, doc_eli = envia(eli, "edx")
ok(r.status_code == 303 and doc_eli, "editor-chefe também pode enviar")
ok(envia(ivo, "edx")[0].status_code == 403, "corpo editorial não envia")
ok(envia(yara, "edx")[0].status_code == 400, "quem está fora não alcança a revista")
r, doc_iny = envia(eli, "iny")
ok(r.status_code == 303 and cfg_de(doc_iny)["organizacao"] == oy["id"], "Eli envia para a revista do Instituto Y, e o documento fica lá")
zed = cliente("Zed", "zed@exemplo.org")
r, doc_zed = envia(zed, "rdp")
ok(r.status_code == 303 and cfg_de(doc_zed)["organizacao"] is None, "revista de catálogo: qualquer cliente envia (sem organização, o documento é só dele)")
ok(envia(zed, "edx")[0].status_code == 400, "mas não para a revista de uma organização em que não está")
ok(envia(rita, "edx")[0].status_code == 303, "o admin que também é membro envia (é secretaria nas revistas)")

# ---------------------------------------------------------------- 5. matriz: ver
ok(eli.get(f"/doc/{doc_sol}").status_code == 200 and ivo.get(f"/doc/{doc_sol}").status_code == 200 and rita.get(f"/doc/{doc_sol}").status_code == 200,
   "editor-chefe, corpo editorial e admin da organização veem o documento")
ok(yara.get(f"/doc/{doc_sol}").status_code == 403 and zed.get(f"/doc/{doc_sol}").status_code == 403, "outra organização e quem está fora: não")
ok(sol.get(f"/doc/{doc_iny}").status_code == 403 and rita.get(f"/doc/{doc_iny}").status_code == 403 and ivo.get(f"/doc/{doc_iny}").status_code == 403,
   "documento do Instituto Y: nem Sol, nem Ivo, nem Rita (admin da Editora) veem")
ok(eli.get(f"/doc/{doc_iny}").status_code == 200 and yara.get(f"/doc/{doc_iny}").status_code == 200, "Eli (secretaria) e Yara (admin) veem")
pi = ivo.get("/painel").text
ok(doc_sol in pi and doc_iny not in pi and doc_zed not in pi, "a lista de documentos segue a mesma regra")
ok(doc_sol in adm.get("/admin/documentos").text and doc_iny in adm.get("/admin/documentos").text, "o staff vê tudo numa fila só")
ok(zed.get(f"/doc/{doc_zed}").status_code == 200 and sol.get(f"/doc/{doc_zed}").status_code == 403, "documento de quem está sem organização é só dele")

# ---------------------------------------------------------------- 6. matriz: corrigir
ok(sol.get(f"/doc/{doc_eli}/editar").status_code == 200, "secretaria corrige o documento de outra pessoa da mesma revista")
ok(ivo.get(f"/doc/{doc_sol}/editar").status_code == 403 and ivo.post(f"/doc/{doc_sol}/etapa", data={"etapa": "em_revisao"}).status_code == 403,
   "corpo editorial não corrige nem muda etapa")
ok(eli.get(f"/doc/{doc_sol}/editar").status_code == 403, "editor-chefe não corrige o que não enviou")
ok(eli.get(f"/doc/{doc_eli}/editar").status_code == 200, "mas corrige o que ele mesmo enviou")
nina = cliente("Nina", "nina@exemplo.org")
ORGS.define_admin(ox["id"], uid("nina@exemplo.org"), True)
ok(nina.get(f"/doc/{doc_sol}").status_code == 200 and nina.get(f"/doc/{doc_sol}/editar").status_code == 403 and envia(nina, "edx")[0].status_code == 403,
   "admin da organização sem papel na revista: vê tudo dela, não corrige nem envia")
ok("edx" in nina.get("/revistas").text and 'value="edx"' in nina.get("/").text, "e vê as revistas da organização que administra")
ok(A.pode({"id": "api", "papel": "admin"}, "depositar") and not A.pode(CONTAS.por_id(uid("rita@exemplo.org")), "depositar"),
   "depositar na SciELO é só do staff")
ok(A.pode(CONTAS.por_id(uid("rita@exemplo.org")), "ver_uso", ox["id"]) and A.pode(CONTAS.por_id(uid("rita@exemplo.org")), "gerenciar_pessoas", ox["id"])
   and not A.pode(CONTAS.por_id(uid("rita@exemplo.org")), "ver_uso", oy["id"]) and not A.pode(CONTAS.por_id(uid("sol@exemplo.org")), "ver_uso", ox["id"])
   and A.pode({"id": "api", "papel": "admin"}, "ver_uso", oy["id"]), "uso e pessoas: o admin da própria organização e o staff administrador")

# ---------------------------------------------------------------- 7. aprovação do editor-chefe e entrega
r = eli.post(f"/doc/{doc_sol}/aprovar")
ok(r.status_code == 303 and "erro=" in r.headers["location"] and "aprovacao" not in cfg_de(doc_sol), "não aprova XML que ainda não está pronto")
ok(sol.post(f"/doc/{doc_sol}/aprovar").status_code == 403 and ivo.post(f"/doc/{doc_sol}/aprovar").status_code == 403
   and rita.post(f"/doc/{doc_sol}/aprovar").status_code == 403 and adm.post(f"/doc/{doc_sol}/aprovar").status_code == 403, "só o editor-chefe aprova")
completa(sol, doc_sol, "edx")
v = val_de(doc_sol)
ok(v.get("pronto"), f"o documento fica pronto depois da revisão (bloqueantes: {v.get('bloqueantes')}; packtools: {v.get('packtools')})")
ok(A.entrega_liberada(cfg_de(doc_sol))[0] is False, "revista com editor-chefe: entrega bloqueada sem aprovação")
r = adm.post(f"/doc/{doc_sol}/entrega")
ok(r.status_code == 303 and "editor-chefe" in loc(r), "depositar por artigo avisa que falta a aprovação do editor-chefe")
r = eli.post(f"/doc/{doc_sol}/aprovar", data={"nota": "revisado pelo comitê"})
cfg = cfg_de(doc_sol)
ok(r.status_code == 303 and "mensagem" in r.headers["location"] and cfg.get("aprovacao", {}).get("por") == "Eli" and cfg.get("etapa") == "aprovado"
   and any(h.get("etapa") == "aprovado" and h.get("nota") == "revisado pelo comitê" for h in cfg.get("historico_etapas", [])),
   "o editor-chefe aprova: aprovação e etapa 'aprovado' no histórico")
ok(A.entrega_liberada(cfg)[0] is True, "com a aprovação a entrega fica liberada")
r = adm.post(f"/doc/{doc_sol}/entrega")
ok(r.status_code == 303 and "editor-chefe" not in loc(r), "depositar passa da trava do editor-chefe (o que falta agora é o FTP)")
ok("já estava aprovado" in loc(eli.post(f"/doc/{doc_sol}/aprovar")), "aprovar de novo não duplica")
ok(sol.post(f"/doc/{doc_eli}/etapa", data={"etapa": "aprovado"}).status_code == 400, "a etapa Aprovado não é marcada à mão")
completa(sol, doc_sol, "edx")
cfg = cfg_de(doc_sol)
ok("aprovacao" not in cfg and cfg.get("etapa") == "em_revisao" and any("desfeita" in (h.get("nota") or "") for h in cfg["historico_etapas"]),
   "corrigir depois da aprovação desfaz a aprovação (o XML mudou)")
ok(A.entrega_liberada(cfg_de(doc_iny))[0] is True, "revista sem editor-chefe: entrega segue como antes")
try:
    L.cria([doc_sol], 1, "teste")
    ok(False, "lote com XML sem aprovação deveria ser recusado")
except ValueError as e:
    ok("editor-chefe" in str(e), f"lote recusa XML sem aprovação do editor-chefe ({e})")
etapas = [c for c, _ in M.ETAPAS]
ok(etapas.index("aprovado") == etapas.index("pronto") + 1 and etapas.index("entregue") == etapas.index("aprovado") + 1,
   "a etapa 'Aprovado pelo editor-chefe' fica entre Pronto e Entregue")
ok("Aprovado pelo editor-chefe" in sol.get("/ajuda").text, "Como funciona explica a etapa")

# ---------------------------------------------------------------- 8. organização pessoal e cadastro de revista
ok(zed.post("/revistas/nova", data=dict(form_rev, acronimo="zed", titulo="Revista do Zed", issn_epub="1111-1119", doi_prefixo="10.99999/zed")).status_code == 303,
   "quem não está em organização nenhuma cadastra revista")
oz = ORGS.por_id(A.organizacao_da_revista("zed"))
ok(oz and oz["nome"] == "Organização de Zed" and uid("zed@exemplo.org") in oz["admins"] and A.papel_em(uid("zed@exemplo.org"), "zed") == "secretaria_editorial",
   "e ganha uma organização pessoal, que administra, com secretaria na revista")
ok(CONTAS.por_id(uid("zed@exemplo.org"))["organizacao"] == oz["id"] and "Organização de Zed" in zed.get("/conta").text, "a organização pessoal aparece em Minha conta")
ok(envia(zed, "zed")[0].status_code == 303, "e envia para a revista dela")
ok(zed.post("/revistas/nova", data=dict(form_rev, acronimo="zed2", titulo="Segunda do Zed", issn_epub="3333-3335", doi_prefixo="10.99999/zed2")).status_code == 303
   and A.organizacao_da_revista("zed2") == oz["id"], "a segunda revista vai para a mesma organização pessoal")
ok(zed.get(f"/revistas/consulta?numero=1413-9936").json().get("oculta"), "ISSN de revista de outra organização segue oculto")

# ---------------------------------------------------------------- 9. revista muda de organização, vira de catálogo, é removida
form_edit = {k: v for k, v in next(x for x in M.carrega_revistas() if x["acronimo"] == "edx").items() if isinstance(v, str)}
ok(adm.post("/revistas/edx", data=dict(form_edit, visibilidade="publica")).status_code == 303 and A.organizacao_da_revista("edx") is None
   and A.quem_tem("edx") == [], "revista que vira de catálogo fica sem papéis")
ok(A.entrega_liberada(cfg_de(doc_sol))[0] is True, "sem editor-chefe, a entrega volta a ser livre")
ok(adm.post("/revistas/edx", data=dict(form_edit, visibilidade=f"org:{oy['id']}")).status_code == 303 and A.organizacao_da_revista("edx") == oy["id"]
   and A.papel_em(uid("yara@exemplo.org"), "edx") == "secretaria_editorial" and A.papel_em(uid("eli@exemplo.org"), "edx") == "secretaria_editorial"
   and A.papel_em(uid("sol@exemplo.org"), "edx") is None, "revista que passa para outra organização: os membros dela viram secretaria")
ok("edx" not in sol.get("/revistas").text and sol.get(f"/doc/{doc_eli}").status_code == 403 and yara.get(f"/doc/{doc_eli}").status_code == 200,
   "quem ficou para trás perde a revista e os documentos dela; a organização nova passa a ver")
ok(adm.post("/revistas/zed2/remover").status_code == 303 and A.quem_tem("zed2") == [], "remover a revista limpa os papéis")

# ---------------------------------------------------------------- 10. administrador vincula e desvincula pelo painel
r = adm.post(f"/usuarios/{uid('zed@exemplo.org')}/organizacao", data={"organizacao": ox["id"]})
ok(r.status_code == 303 and uid("zed@exemplo.org") in ORGS.por_id(ox["id"])["membros"] and CONTAS.por_id(uid("zed@exemplo.org"))["organizacao"] == ox["id"],
   "vincular pelo painel: entra como membro e a organização vira a principal")
ok(uid("zed@exemplo.org") in ORGS.por_id(oz["id"])["admins"], "sem perder a organização pessoal")
ok("erro" in adm.post(f"/usuarios/{uid('zed@exemplo.org')}/organizacao", data={"organizacao": ox["id"]}).headers["location"], "vincular de novo é recusado")
r = adm.post(f"/usuarios/{uid('zed@exemplo.org')}/organizacao", data={"organizacao": ""})
ok(r.status_code == 303 and uid("zed@exemplo.org") not in ORGS.por_id(ox["id"])["membros"] and CONTAS.por_id(uid("zed@exemplo.org"))["organizacao"] == oz["id"],
   "desvincular tira da principal e o espelho volta para a que sobrou")
ok("erro" in adm.post(f"/admin/organizacoes/{oz['id']}/remover").headers["location"], "organização com pessoas (ou revistas) não é removida")
ok("(admin)" in adm.get("/admin/organizacoes").text, "a página Organizações marca quem administra")

# ---------------------------------------------------------------- 11. migração dos dados de antes (organizacao na conta, revista com dono)
CONTAS.cria("old1@exemplo.org", "Old Um", "senha-forte-1", "cliente")
CONTAS.cria("old2@exemplo.org", "Old Dois", "senha-forte-1", "cliente")
CONTAS.cria("old3@exemplo.org", "Old Três", "senha-forte-1", "cliente")
CONTAS.cria("old4@exemplo.org", "Old Quatro", "senha-forte-1", "cliente")
u1, u2, u3, u4 = (uid(f"old{i}@exemplo.org") for i in (1, 2, 3, 4))
arq_org = os.path.join(tmp, "organizacoes.json")
dados = json.load(io.open(arq_org, encoding="utf-8"))
dados["organizacoes"].append({"id": "antiga01", "nome": "Editora Antiga", "convite": "ANTIGA01", "criado_em": "2026-09-01T10:00:00-03:00", "criado_por": u1})
io.open(arq_org, "w", encoding="utf-8").write(json.dumps(dados, ensure_ascii=False))
CONTAS.define_organizacao(u1, "antiga01")
CONTAS.define_organizacao(u2, "antiga01")
CONTAS.define_organizacao(u4, "sumiu")
lista = M.carrega_revistas()
lista.append(dict(form_rev, acronimo="olda", titulo="Revista da Antiga", issn_epub="4444-4443", organizacao="antiga01"))
lista.append(dict(form_rev, acronimo="oldp", titulo="Revista Particular", issn_epub="5555-5551", dono=u3))
M.grava_revistas(lista)
feito = A.migra(forcar=True)
ant = ORGS.por_id("antiga01")
ok(feito["migrado"] and u1 in ant["admins"] and u1 in ant["membros"] and u2 in ant["membros"] and u2 not in ant["admins"],
   f"migração: quem estava na organização vira membro; quem a criou (cliente) vira admin ({feito})")
ok(A.papel_em(u1, "olda") == "secretaria_editorial" and A.papel_em(u2, "olda") == "secretaria_editorial", "membros viram secretaria nas revistas da organização")
rp = next(x for x in M.carrega_revistas() if x["acronimo"] == "oldp")
op = ORGS.por_id(rp.get("organizacao"))
ok("dono" not in rp and op and op["nome"] == "Organização de Old Três" and u3 in op["admins"] and A.papel_em(u3, "oldp") == "secretaria_editorial"
   and CONTAS.por_id(u3)["organizacao"] == op["id"], "revista particular vira de uma organização pessoal de quem a cadastrou")
ok(CONTAS.por_id(u4).get("organizacao") is None, "conta apontando para organização que não existe é limpa")
ok(CONTAS.por_id(u1)["organizacao"] == "antiga01", "o espelho de quem já estava certo não muda")
ok(A.migra() == {"migrado": False} and json.load(io.open(os.path.join(tmp, "papeis.json"), encoding="utf-8")).get("migrado") is True,
   "a migração roda uma vez só (marcada em papeis.json)")
ok(not any("papel_revista" in u or "papeis" in u for u in CONTAS.lista()), "a permissão não vira campo na conta")

print("\nFALHAS:", len(falhas))
for f in falhas:
    print("  -", f)
shutil.rmtree(tmp, ignore_errors=True)
sys.exit(1 if falhas else 0)
