"""Autorização num lugar só (etapa 2 do multi-tenant; ver multitenancy_proposta_v1.md e PROMPT_MULTITENANCY_XML_JATS.md).

A permissão de uma pessoa nunca é um campo único na conta. Ela mora em:
- `papeis.json` — o papel POR REVISTA: editor_chefe, corpo_editorial ou secretaria_editorial (uma pessoa pode ter
  papéis diferentes em revistas diferentes, inclusive de organizações diferentes);
- `organizacoes.json` — `admins` (gerenciam pessoas, papéis e revistas; veem tudo da organização e o uso) e
  `membros` (entraram pelo convite; ganham secretaria editorial em todas as revistas da organização, inclusive nas
  criadas depois).
O `papel` da conta continua dizendo só o tipo global: cliente, operador (staff) ou admin (staff).

Regras:
- Revista de trabalho pertence a uma organização. Revista sem organização é do catálogo (semeada por nós): qualquer
  cliente envia para ela e, nela, o documento fica visível para os colegas da organização de quem enviou (como era).
- Documento: vê quem tem papel na revista dele, o admin da organização, quem enviou e o staff.
- Corrige (revisar/editar, etapa, figuras, reprocessar) a secretaria editorial, quem enviou e o staff.
- Aprova o XML para entrega só o editor-chefe da revista; se a revista tem editor-chefe, a entrega (por artigo ou
  lote) exige a aprovação. Gerar o XML de novo desfaz a aprovação.
- Deposita na SciELO só o staff. Cadastra revista o staff, o admin da organização (nela) e quem ainda não está em
  organização nenhuma (ganha uma organização pessoal com o próprio nome).
- `usuarios.json[organizacao]` vira só um espelho ("organização principal", a que Minha conta mostra).

Tudo que decide "pode ou não pode" passa por `pode(usuario, acao, alvo)`; as rotas não repetem regra.
"""
from typing import List, Optional, Tuple

PAPEIS_REVISTA = ("editor_chefe", "corpo_editorial", "secretaria_editorial")
ROTULO_PAPEL_REVISTA = {"editor_chefe": "editor-chefe", "corpo_editorial": "corpo editorial", "secretaria_editorial": "secretaria editorial"}
ACOES = ("enviar", "corrigir", "aprovar", "ver_status", "depositar", "ver_uso", "gerenciar_pessoas", "criar_revista")
_cfg: dict = {}


def configura(data, le_json, grava_json, agora_iso, carrega_revistas, grava_revistas, orgs, contas) -> None:
    _cfg.update(data=data, le=le_json, grava=grava_json, agora=agora_iso, revistas=carrega_revistas,
                grava_revistas=grava_revistas, orgs=orgs, contas=contas)


# ---------------------------------------------------------------- papeis.json (a tabela de junção pessoa × revista)

def _arquivo():
    return _cfg["data"] / "papeis.json"


def _bruto() -> dict:
    return _cfg["le"](_arquivo(), {}) or {}


def _papeis() -> list:
    return list(_bruto().get("papeis") or [])


def _grava_papeis(lista: list, extra: Optional[dict] = None) -> None:
    dados = _bruto()
    dados["papeis"] = lista
    if extra:
        dados.update(extra)
    _cfg["grava"](_arquivo(), dados)


def papeis_de(uid: Optional[str]) -> List[dict]:
    return [p for p in _papeis() if uid and p.get("usuario") == uid]


def papel_em(uid: Optional[str], revista: Optional[str]) -> Optional[str]:
    if not uid or not revista:
        return None
    return next((p["papel"] for p in _papeis() if p.get("usuario") == uid and p.get("revista") == revista), None)


def quem_tem(revista: str, papel: Optional[str] = None) -> List[str]:
    return [p["usuario"] for p in _papeis() if p.get("revista") == revista and (papel is None or p.get("papel") == papel)]


def revistas_com_papel(uid: Optional[str]) -> set:
    return {p["revista"] for p in _papeis() if uid and p.get("usuario") == uid}


def define_papel(uid: str, revista: str, papel: Optional[str], por: str = "") -> None:
    """Um papel por pessoa por revista; `papel=None` remove."""
    if not uid or not revista:
        raise ValueError("Conta e revista são obrigatórias.")
    if papel is not None and papel not in PAPEIS_REVISTA:
        raise ValueError("Papel inválido: use editor_chefe, corpo_editorial ou secretaria_editorial.")
    lista = [p for p in _papeis() if not (p.get("usuario") == uid and p.get("revista") == revista)]
    if papel:
        lista.append({"usuario": uid, "revista": revista, "papel": papel, "desde": _cfg["agora"](), "por": por})
    _grava_papeis(lista)


def ao_renomear_revista(de: str, para: str) -> None:
    if de == para:
        return
    lista = _papeis()
    for p in lista:
        if p.get("revista") == de:
            p["revista"] = para
    _grava_papeis(lista)


def ao_remover_revista(acronimo: str) -> None:
    _grava_papeis([p for p in _papeis() if p.get("revista") != acronimo])


# ---------------------------------------------------------------- staff e organizações

def e_staff(usuario: Optional[dict]) -> bool:
    return (usuario or {}).get("papel") in ("admin", "operador")


def organizacoes_admin(uid: Optional[str]) -> List[str]:
    return [o["id"] for o in _cfg["orgs"].lista() if uid and uid in o["admins"]]


def organizacoes_membro(uid: Optional[str]) -> List[str]:
    return [o["id"] for o in _cfg["orgs"].lista() if uid and uid in o["membros"]]


def organizacoes_de(uid: Optional[str]) -> List[str]:
    """Todas as organizações da pessoa (administra ou é membro), sem repetir."""
    vistos: List[str] = []
    for oid in organizacoes_admin(uid) + organizacoes_membro(uid):
        if oid not in vistos:
            vistos.append(oid)
    return vistos


def e_admin_org(usuario: Optional[dict], oid: Optional[str]) -> bool:
    o = _cfg["orgs"].por_id(oid) if oid else None
    return bool(o) and (usuario or {}).get("id") in o["admins"]


def organizacao_principal(usuario: Optional[dict]) -> Optional[dict]:
    """A organização que a conta mostra em Minha conta: a do espelho `organizacao`, se ainda vale; senão a primeira."""
    uid = (usuario or {}).get("id")
    lista = organizacoes_de(uid)
    if not lista:
        return None
    oid = (usuario or {}).get("organizacao")
    return _cfg["orgs"].por_id(oid if oid in lista else lista[0])


def _sincroniza_principal(uid: str, preferida: Optional[str] = None) -> None:
    """`usuarios.json[organizacao]` é só um espelho para as telas; quem decide acesso é este módulo."""
    conta = _cfg["contas"].por_id(uid)
    if not conta:
        return
    lista = organizacoes_de(uid)
    atual = conta.get("organizacao")
    if preferida and preferida in lista:
        novo = preferida
    elif atual in lista:
        novo = atual
    else:
        novo = lista[0] if lista else None
    if novo != atual:
        _cfg["contas"].define_organizacao(uid, novo)


def revistas_da_organizacao(oid: str) -> List[dict]:
    return [r for r in _cfg["revistas"]() if r.get("organizacao") == oid]


def organizacao_da_revista(acronimo: Optional[str]) -> Optional[str]:
    if not acronimo:
        return None
    rev = next((r for r in _cfg["revistas"]() if r.get("acronimo") == acronimo), None)
    return (rev or {}).get("organizacao")


def entrar_na_organizacao(uid: str, oid: str, por: str = "", como_admin: bool = False, principal: bool = False) -> None:
    """Membro novo ganha secretaria editorial em todas as revistas da organização (o admin dela ajusta depois)."""
    o = _cfg["orgs"].por_id(oid)
    if not o:
        raise ValueError("Organização não encontrada.")
    if uid in o["membros"] and (not como_admin or uid in o["admins"]):
        raise ValueError("Esta conta já está nesta organização.")
    _cfg["orgs"].adiciona_membro(oid, uid, admin=como_admin)
    for r in revistas_da_organizacao(oid):
        if not papel_em(uid, r["acronimo"]):
            define_papel(uid, r["acronimo"], "secretaria_editorial", por)
    _sincroniza_principal(uid, preferida=oid if principal else None)


def sair_da_organizacao(uid: str, oid: str) -> None:
    """Sai da organização e perde os papéis nas revistas dela."""
    _cfg["orgs"].remove_membro(oid, uid)
    for r in revistas_da_organizacao(oid):
        define_papel(uid, r["acronimo"], None)
    _sincroniza_principal(uid)


def ao_criar_revista(revista: dict, usuario: Optional[dict] = None, por: str = "") -> None:
    """Revista nova dentro de uma organização: os membros ganham secretaria; quem criou (cliente) também."""
    oid = revista.get("organizacao")
    acr = revista.get("acronimo")
    if not oid or not acr:
        return
    o = _cfg["orgs"].por_id(oid) or {"membros": []}
    for uid in o["membros"]:
        if not papel_em(uid, acr):
            define_papel(uid, acr, "secretaria_editorial", por)
    uid = (usuario or {}).get("id")
    if uid and not e_staff(usuario) and not papel_em(uid, acr):
        define_papel(uid, acr, "secretaria_editorial", por)


def ao_mudar_organizacao(acronimo: str, de: Optional[str], para: Optional[str], por: str = "") -> None:
    """Revista que muda de organização: quem era da antiga (e não é da nova) perde o papel; os membros da nova
    ganham secretaria. Revista que vira de catálogo (pública) fica sem papéis."""
    if de == para:
        return
    if not para:
        ao_remover_revista(acronimo)
        return
    orgs = _cfg["orgs"]
    saem = set(orgs.pessoas(de)) - set(orgs.pessoas(para)) if de else set()
    for uid in quem_tem(acronimo):
        if uid in saem:
            define_papel(uid, acronimo, None)
    for uid in (orgs.por_id(para) or {"membros": []})["membros"]:
        if not papel_em(uid, acronimo):
            define_papel(uid, acronimo, "secretaria_editorial", por)


def organizacao_pessoal(usuario: dict) -> str:
    """Cliente sem organização que cadastra uma revista ganha a sua, com o nome dele, e vira admin (e membro) dela."""
    base = f"Organização de {(usuario.get('nome') or 'cliente')[:60]}"
    nome, n = base, 2
    while True:
        try:
            o = _cfg["orgs"].cria(nome, por=usuario["id"])
            break
        except ValueError:
            nome = f"{base} ({n})"
            n += 1
            if n > 50:
                raise
    entrar_na_organizacao(usuario["id"], o["id"], por=usuario.get("nome") or "", como_admin=True)
    return o["id"]


def organizacao_para_nova_revista(usuario: dict) -> Optional[str]:
    """Revista cadastrada por cliente: fica na organização que ele administra; senão na de que é membro; senão numa
    organização pessoal criada na hora. Staff cadastra revista de catálogo (pública)."""
    if e_staff(usuario):
        return None
    uid = usuario.get("id")
    admins = organizacoes_admin(uid)
    if admins:
        return admins[0]
    membro = organizacoes_membro(uid)
    if membro:
        return membro[0]
    return organizacao_pessoal(usuario)


def organizacao_do_envio(usuario: dict, revista: Optional[str]) -> Optional[str]:
    """Organização gravada no documento: a da revista; sem revista (ou revista de catálogo), a principal de quem envia."""
    return organizacao_da_revista(revista) or ((organizacao_principal(usuario) or {}).get("id"))


# ---------------------------------------------------------------- visibilidade

def revistas_de(usuario: Optional[dict]) -> List[dict]:
    """Revistas ao alcance: catálogo (sem organização) + revistas onde tem papel + revistas das organizações que
    administra. Staff vê todas."""
    todas = _cfg["revistas"]()
    if e_staff(usuario):
        return todas
    uid = (usuario or {}).get("id")
    com_papel = revistas_com_papel(uid)
    minhas = set(organizacoes_admin(uid))
    return [r for r in todas if not r.get("organizacao") or r["acronimo"] in com_papel or r.get("organizacao") in minhas]


def _e_autor(doc: dict, usuario: dict) -> bool:
    return (doc.get("criado_por_id") or doc.get("criado_por")) in (usuario.get("id"), usuario.get("nome"))


def _papel_efetivo(usuario: dict, doc: dict) -> Optional[str]:
    """Papel da pessoa no documento: o papel na revista dele; em revista de catálogo (ou documento sem revista),
    os colegas da organização de quem enviou agem como secretaria editorial (regra de antes dos papéis)."""
    uid = usuario.get("id")
    acr = doc.get("revista")
    papel = papel_em(uid, acr)
    if papel:
        return papel
    if not organizacao_da_revista(acr) and doc.get("organizacao") and doc["organizacao"] in organizacoes_membro(uid):
        return "secretaria_editorial"
    return None


def pode_ver_doc(doc: dict, usuario: Optional[dict]) -> bool:
    if e_staff(usuario):
        return True
    u = usuario or {}
    uid = u.get("id")
    if not uid:
        return False
    if _e_autor(doc, u) or _papel_efetivo(u, doc):
        return True
    org_doc = organizacao_da_revista(doc.get("revista")) or doc.get("organizacao")
    return bool(org_doc) and org_doc in organizacoes_admin(uid)


# ---------------------------------------------------------------- a matriz

def pode(usuario: Optional[dict], acao: str, alvo=None) -> bool:
    """`alvo`: acrônimo da revista (enviar), config do documento (corrigir, aprovar, ver_status, depositar) ou id da
    organização (ver_uso, gerenciar_pessoas). `criar_revista` não tem alvo."""
    if acao not in ACOES:
        raise ValueError(f"Ação desconhecida: {acao}")
    u = usuario or {}
    uid = u.get("id")
    if acao == "enviar":
        if e_staff(u):
            return True
        if not alvo or not organizacao_da_revista(alvo):
            return True  # sem revista escolhida (detectar pelo ISSN) ou revista de catálogo: qualquer cliente envia
        return papel_em(uid, alvo) in ("secretaria_editorial", "editor_chefe")
    if acao == "corrigir":
        doc = alvo or {}
        return e_staff(u) or _e_autor(doc, u) or _papel_efetivo(u, doc) == "secretaria_editorial"
    if acao == "aprovar":
        return not e_staff(u) and papel_em(uid, (alvo or {}).get("revista")) == "editor_chefe"
    if acao == "ver_status":
        return pode_ver_doc(alvo or {}, u)
    if acao == "depositar":
        return e_staff(u)
    if acao in ("ver_uso", "gerenciar_pessoas"):
        return u.get("papel") == "admin" or e_admin_org(u, alvo)
    if acao == "criar_revista":
        return e_staff(u) or bool(organizacoes_admin(uid)) or not organizacoes_de(uid)
    return False


def entrega_liberada(doc: dict) -> Tuple[bool, str]:
    """Revista com editor-chefe: o XML precisa da aprovação dele antes do depósito (artigo ou lote)."""
    acr = doc.get("revista")
    if acr and quem_tem(acr, "editor_chefe") and not ((doc.get("aprovacao") or {}).get("em")):
        return False, "A revista tem editor-chefe cadastrado: o XML precisa ser aprovado por ele antes da entrega."
    return True, ""


def registra_aprovacao(cfg: dict, usuario: dict, nota: str = "") -> None:
    """Aprovação do editor-chefe no config do documento (quem grava é a rota)."""
    agora = _cfg["agora"]()
    cfg["aprovacao"] = {"por": usuario.get("nome"), "por_id": usuario.get("id"), "em": agora, "nota": nota or None}
    cfg["etapa"] = "aprovado"
    cfg.setdefault("historico_etapas", []).append({"etapa": "aprovado", "por": usuario.get("nome"), "em": agora,
                                                   "nota": nota or "XML aprovado pelo editor-chefe"})


def desfaz_aprovacao(cfg: dict, motivo: str) -> bool:
    """A aprovação vale para um XML: gerado de novo, precisa de nova aprovação. Devolve True se havia aprovação."""
    ap = cfg.pop("aprovacao", None)
    if not ap:
        return False
    if cfg.get("etapa") == "aprovado":
        cfg["etapa"] = "em_revisao"
    cfg.setdefault("historico_etapas", []).append({"etapa": cfg.get("etapa") or "em_revisao", "por": "sistema", "em": _cfg["agora"](),
                                                   "nota": f"aprovação de {ap.get('por')} desfeita: {motivo}"})
    return True


# ---------------------------------------------------------------- migração (uma vez, ao subir a versão)

def migra(forcar: bool = False) -> dict:
    """Dados de antes dos papéis por revista: quem tinha `organizacao` na conta vira membro (e quem criou a organização,
    sendo cliente, vira admin); membro ganha secretaria em todas as revistas da organização; revista 'particular'
    (`dono`) passa para uma organização pessoal de quem a cadastrou. Idempotente: marca papeis.json."""
    bruto = _bruto()
    if bruto.get("migrado") and not forcar:
        return {"migrado": False}
    contas, orgs = _cfg["contas"], _cfg["orgs"]
    usuarios = contas.lista()
    ids = {u["id"]: u for u in usuarios}
    feito = {"migrado": True, "membros": 0, "admins": 0, "papeis": 0, "pessoais": 0}
    # 1. quem estava na organização vira membro; quem a criou (cliente) administra
    for o in orgs.lista():
        criador = o.get("criado_por")
        criador_cliente = criador in ids and ids[criador].get("papel") == "cliente"
        for u in usuarios:
            if u.get("organizacao") == o["id"] and u["id"] not in o["membros"]:
                orgs.adiciona_membro(o["id"], u["id"])
                feito["membros"] += 1
        if criador_cliente and criador not in o["admins"]:
            orgs.adiciona_membro(o["id"], criador, admin=True)
            feito["admins"] += 1
    # 2. revista particular vira de uma organização pessoal (ninguém ganha acesso que não tinha)
    revistas = _cfg["revistas"]()
    mudou = False
    for r in revistas:
        if "dono" not in r:
            continue
        dono = r.pop("dono")
        mudou = True
        if dono and not r.get("organizacao") and dono in ids:
            r["organizacao"] = organizacao_pessoal(ids[dono])
            feito["pessoais"] += 1
    if mudou:
        _cfg["grava_revistas"](revistas)
    # 3. membro tem secretaria em todas as revistas da organização
    for o in orgs.lista():
        for r in revistas_da_organizacao(o["id"]):
            for uid in orgs.pessoas(o["id"]):
                if uid in ids and not papel_em(uid, r["acronimo"]):
                    define_papel(uid, r["acronimo"], "secretaria_editorial", "migração")
                    feito["papeis"] += 1
    # 4. o espelho da conta aponta para uma organização que existe
    for u in usuarios:
        _sincroniza_principal(u["id"])
    _grava_papeis(_papeis(), {"migrado": True, "migrado_em": _cfg["agora"]()})
    return feito
