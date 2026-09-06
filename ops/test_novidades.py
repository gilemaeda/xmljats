"""Novidades por versão: janela ao entrar depois de uma atualização, página de notificações e filtro por papel
(nada do painel administrativo chega ao cliente)."""
import os
import shutil
import sys
if hasattr(sys.stdout, "reconfigure"):  # console cp1252 do Windows nao imprime todo Unicode e derrubava o teste
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import tempfile

tmp = tempfile.mkdtemp(prefix="xmljats-nov-")
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


MODAL = 'id="novidades-modal"'
SO_ADMIN = [i["titulo"] for v in N.VERSOES for i in v["itens"] if i["para"] == "admin"]

# ---------------------------------------------------------------- 1. o módulo
ok(M.VERSAO_APP == N.ATUAL, f"a versão do app ({M.VERSAO_APP}) é a primeira das novidades ({N.ATUAL})")
chaves = [N.chave(v["versao"]) for v in N.VERSOES]
ok(chaves == sorted(chaves, reverse=True) and len(set(chaves)) == len(chaves), "versões em ordem decrescente, sem repetição")
ok(len(SO_ADMIN) >= 3, f"há itens só do painel administrativo para provar o filtro ({len(SO_ADMIN)})")
ok(all(i["para"] == "todos" for v in N.visiveis("cliente") for i in v["itens"]), "cliente só vê itens 'todos'")
ok(all(i["para"] != "admin" for v in N.visiveis("operador") for i in v["itens"]), "operador não vê item 'admin'")
ok(any(i["para"] == "admin" for v in N.visiveis("admin") for i in v["itens"]), "administrador vê os itens do painel")
ok(all(v["itens"] for v in N.visiveis("cliente")), "versão sem item visível some da lista")
ok(N.linha_de_base({"id": "local", "papel": "admin"}) == N.ATUAL, "modo local (sem conta) nunca tem novidade pendente")
ok(N.linha_de_base({"id": "x", "papel": "cliente", "atividade": {"ultimo_acesso": "2026-09-06T09:00:00-03:00"}}) == "0.17.0",
   "conta antiga sem registro: o que saiu antes do último acesso não é novidade (base 0.17.0 para acesso em 06/09)")
ok(N.linha_de_base({"id": "x", "papel": "cliente", "atividade": {"ultimo_acesso": "2026-09-05T09:00:00-03:00"}}) is None,
   "acesso anterior a todas as versões: tudo é novidade")
ok(N.linha_de_base({"id": "x", "papel": "cliente", "novidades_vistas": "0.20.0"}) == "0.20.0", "o registro de 'visto' manda")

# hierarquia de públicos, com uma versão de prova
prova = {"versao": "9.9.9", "data": "2099-01-01", "itens": [
    {"para": "todos", "titulo": "Prova todos", "texto": "t"}, {"para": "operador", "titulo": "Prova operador", "texto": "o"},
    {"para": "admin", "titulo": "Prova admin", "texto": "a"}]}
N.VERSOES.insert(0, prova)
try:
    ok([i["titulo"] for i in N.visiveis("cliente")[0]["itens"]] == ["Prova todos"], "cliente: só o item 'todos'")
    ok([i["titulo"] for i in N.visiveis("operador")[0]["itens"]] == ["Prova todos", "Prova operador"], "operador: 'todos' e 'operador'")
    ok([i["titulo"] for i in N.visiveis("admin")[0]["itens"]] == ["Prova todos", "Prova operador", "Prova admin"], "administrador: tudo")
finally:
    N.VERSOES.remove(prova)

# ---------------------------------------------------------------- 2. conta nova: nada é novidade
c = TestClient(app, follow_redirects=False)
reg = c.post("/registrar", data={"nome": "Nova", "email": "n@exemplo.org", "senha": "senha-forte-1", "senha2": "senha-forte-1"},
             headers={"x-forwarded-for": "10.1.1.1"})
c.cookies.set("xmljats_sessao", reg.cookies["xmljats_sessao"])
uid = next(u["id"] for u in M.CONTAS.lista() if u["email"] == "n@exemplo.org")
ok(M.CONTAS.por_id(uid).get("novidades_vistas") == N.ATUAL, "conta nova nasce com a versão atual como vista")
home = c.get("/").text
ok(MODAL not in home, "sem atualização desde o cadastro, não há janela")
ok('href="/novidades"' in home and 'Novidades<span class="n">' not in home, "o sino está no menu, sem contador")

# ---------------------------------------------------------------- 3. o sistema foi atualizado: janela filtrada
M.CONTAS.marca_novidades(uid, "0.19.0")
pend = N.pendentes(M.CONTAS.por_id(uid))
ok([v["versao"] for v in pend] == [v["versao"] for v in N.visiveis("cliente") if N.chave(v["versao"]) > N.chave("0.19.0")],
   f"pendentes = versões visíveis depois da última vista: {[v['versao'] for v in pend]}")
n_itens = N.conta_itens(pend)
pag = c.get("/painel").text
ok(MODAL in pag and "O sistema foi atualizado" in pag, "ao entrar depois da atualização aparece a janela")
ok("SciELO PS 1.10" in pag and "Novidades e notificações" in pag, "a janela traz o que mudou para o cliente")
ok(not any(t in pag for t in SO_ADMIN), "nada do painel administrativo vaza para o cliente")
ok(f'Novidades<span class="n">{n_itens}</span>' in pag, f"o sino conta as {n_itens} novidades não vistas")
np = c.get("/novidades").text
ok(MODAL not in np, "a página Novidades não abre a janela por cima de si mesma")
ok("novo para você" in np and "versão 0.20.0" in np and "versão 0.11.0" in np, "a página lista o histórico e marca o que é novo")
ok(not any(t in np for t in SO_ADMIN), "a página do cliente não tem item do painel administrativo")
ok(M.CONTAS.por_id(uid).get("novidades_vistas") == N.ATUAL, "abrir a página marca como visto")
depois = c.get("/painel").text
ok(MODAL not in depois and 'Novidades<span class="n">' not in depois, "depois disso, sem janela e sem contador")

# ---------------------------------------------------------------- 4. botão 'Entendi'
M.CONTAS.marca_novidades(uid, "0.20.0")
ok(MODAL in c.get("/painel").text, "nova atualização, janela de novo")
r = c.post("/novidades/vista", data={"proximo": "/painel?ordem=aberto"})
ok(r.status_code == 303 and r.headers["location"] == "/painel?ordem=aberto", "'Entendi' volta para onde a pessoa estava")
ok(M.CONTAS.por_id(uid).get("novidades_vistas") == N.ATUAL and MODAL not in c.get("/painel").text, "e marca como visto")
for ruim in ("https://exemplo.org/x", "//exemplo.org", "javascript:alert(1)"):
    r = c.post("/novidades/vista", data={"proximo": ruim})
    ok(r.status_code == 303 and r.headers["location"] == "/", f"destino que não é desta aplicação é ignorado: {ruim}")

# ---------------------------------------------------------------- 5. conta de antes do recurso: usa o último acesso
M.CONTAS._altera(uid, lambda u, _: (u.pop("novidades_vistas", None), u.update(atividade={"ultimo_acesso": "2026-09-05T10:00:00-03:00"})))
pag = c.get("/painel").text
ok(MODAL in pag and "Mais " in pag and "na página Novidades" in pag, "tudo é novidade: a janela mostra as três últimas e aponta o resto para a página")
ok(not any(t in pag for t in SO_ADMIN), "e continua sem item do painel administrativo")

# ---------------------------------------------------------------- 6. operador e administrador
M.CONTAS.cria("op@exemplo.org", "Op", "senha-forte-1", "operador")
op = TestClient(app, follow_redirects=False)
r = op.post("/entrar", data={"email": "op@exemplo.org", "senha": "senha-forte-1", "proximo": "/"}, headers={"x-forwarded-for": "10.1.1.2"})
op.cookies.set("xmljats_sessao", r.cookies["xmljats_sessao"])
pg = op.get("/painel").text
ok(MODAL in pg, "operador criado sem registro vê a janela (base pela data de criação)")
ok(not any(t in pg for t in SO_ADMIN), "operador não vê item do painel administrativo")
adm = TestClient(app, follow_redirects=False)
r = adm.post("/entrar", data={"email": "admin", "senha": "senha-de-teste-123", "proximo": "/"}, headers={"x-forwarded-for": "10.1.1.3"})
adm.cookies.set("xmljats_sessao", r.cookies["xmljats_sessao"])
pa = adm.get("/admin").text
ok(MODAL in pa and any(t in pa for t in SO_ADMIN), "administrador vê os itens do painel na janela")
npa = adm.get("/novidades").text
ok(any(t in npa for t in SO_ADMIN) and "novo para você" in npa, "a página do administrador lista os itens do painel e marca os novos")

# a hierarquia passando pelas telas, com a versão de prova
N.VERSOES.insert(0, prova)
try:
    uid_op = next(u["id"] for u in M.CONTAS.lista() if u["email"] == "op@exemplo.org")
    M.CONTAS.marca_novidades(uid_op, N.ATUAL)
    M.CONTAS.marca_novidades(uid, N.ATUAL)
    pg = op.get("/painel").text
    ok("Prova todos" in pg and "Prova operador" in pg and "Prova admin" not in pg, "na tela, operador vê 'todos' e 'operador', não 'admin'")
    pc = c.get("/painel").text
    ok("Prova todos" in pc and "Prova operador" not in pc and "Prova admin" not in pc, "na tela, cliente vê só 'todos'")
finally:
    N.VERSOES.remove(prova)

ok("Onde vejo o que mudou" in c.get("/ajuda").text, "a ajuda explica onde ver as novidades")

print("\nFALHAS:", len(falhas))
for f in falhas:
    print("  -", f)
shutil.rmtree(tmp, ignore_errors=True)
sys.exit(1 if falhas else 0)
