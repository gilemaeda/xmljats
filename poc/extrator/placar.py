"""Placar: compara o ArticleModel extraido com um gabarito escrito a mao (modelos/gabarito/<nome>.json)
nos seis elementos obrigatorios do plano (secao, titulo, autoria com ORCID, afiliacao, citacoes, referencias)."""
import difflib
import json
import os
from typing import Optional

from .modelo import ArticleModel
from .util import normaliza

ELEMENTOS = ["secao", "titulo", "autoria_orcid", "afiliacao", "citacoes", "referencias"]
ROTULOS = {"secao": "Seção", "titulo": "Título", "autoria_orcid": "Autor + ORCID", "afiliacao": "Afiliação", "citacoes": "Citações", "referencias": "Referências"}
SIMBOLO = {"sim": "sim", "parcial": "parcial", "não": "não", "n/a": "n/a"}


def carrega_gabarito(nome_base) -> Optional[dict]:
    caminho = os.path.join("modelos", "gabarito", nome_base + ".json")
    if not os.path.exists(caminho):
        return None
    with open(caminho, encoding="utf-8") as f:
        return json.load(f)


def _sim(a, b):
    return difflib.SequenceMatcher(None, normaliza(a), normaliza(b)).ratio()


def avalia(model: ArticleModel, gab: Optional[dict]) -> dict:
    r = {}
    if gab is None:
        r["_sem_gabarito"] = True
        r["secao"] = ("?", model.heading or "—")
        r["titulo"] = ("?", (model.titulo_principal or "—")[:70])
        r["autoria_orcid"] = ("?", f"{len(model.autores)} autores, {sum(1 for a in model.autores if a.orcid)} com ORCID")
        r["afiliacao"] = ("?", f"{sum(1 for a in model.autores if a.aff_ids)} autores com afiliação")
        r["citacoes"] = ("?", f"{len({(normaliza(c.autor), c.ano) for c in model.citacoes})} únicas")
        r["referencias"] = ("?", f"{len(model.referencias)} ({model.estilo_referencias})")
        return r
    # secao
    esp = gab.get("heading")
    if not esp:
        r["secao"] = ("n/a", "não consta no PDF")
    elif model.heading and (normaliza(esp) in normaliza(model.heading) or normaliza(model.heading) in normaliza(esp)):
        r["secao"] = ("sim", model.heading)
    elif model.heading:
        r["secao"] = ("parcial", f"achou '{model.heading}', esperado '{esp}'")
    else:
        r["secao"] = ("não", f"esperado '{esp}'")
    # titulo
    esp = gab.get("titulo", "")
    got = model.titulo_principal or ""
    s = _sim(esp, got) if got else 0
    trad_ok = True
    for lang, t in (gab.get("titulos_traduzidos") or {}).items():
        achado = next((x for x in model.titulos if x.tipo == "trans-title" and x.idioma == lang), None)
        if not achado or _sim(t, achado.texto) < 0.9:
            trad_ok = False
    if s >= 0.95 and trad_ok:
        r["titulo"] = ("sim", got[:70])
    elif s >= 0.95:
        r["titulo"] = ("parcial", "título ok; tradução faltando ou com idioma errado")
    elif s >= 0.75:
        r["titulo"] = ("parcial", f"semelhança {s:.2f}: '{got[:60]}'")
    else:
        r["titulo"] = ("não", f"achou '{got[:60]}'")
    # autoria + orcid
    esperados = gab.get("autores", [])
    ok_nome = ok_orcid = 0
    detalhes = []
    for e in esperados:
        sob = normaliza(e["nome"].split()[-1])
        a = next((x for x in model.autores if normaliza(x.sobrenome).endswith(sob) or sob in normaliza(x.nome_completo).split()), None)
        if a:
            ok_nome += 1
            if e.get("orcid") and a.orcid and a.orcid.upper() == e["orcid"].upper():
                ok_orcid += 1
            elif e.get("orcid"):
                detalhes.append(f"ORCID de {e['nome'].split()[-1]}: achou {a.orcid or 'nada'}")
            else:
                ok_orcid += 1  # gabarito sem ORCID (nao consta no PDF)
        else:
            detalhes.append(f"autor '{e['nome']}' não encontrado")
    extras = len(model.autores) - ok_nome
    if ok_nome == len(esperados) and ok_orcid == len(esperados) and extras == 0:
        r["autoria_orcid"] = ("sim", f"{ok_nome} autores, ORCID ok")
    elif ok_nome == len(esperados):
        r["autoria_orcid"] = ("parcial", "; ".join(detalhes) or f"{extras} autor(es) a mais")
    elif ok_nome > 0:
        r["autoria_orcid"] = ("parcial", "; ".join(detalhes))
    else:
        r["autoria_orcid"] = ("não", "; ".join(detalhes) or "nenhum autor")
    # afiliacao
    ok_aff = 0
    det = []
    for e in esperados:
        sob = normaliza(e["nome"].split()[-1])
        a = next((x for x in model.autores if normaliza(x.sobrenome).endswith(sob) or sob in normaliza(x.nome_completo).split()), None)
        affs = [x for x in model.afiliacoes if a and x.id in a.aff_ids]
        inst_esp = normaliza(e.get("instituicao", ""))
        achou_inst = any(inst_esp and (inst_esp in normaliza(x.instituicao or "") or inst_esp in normaliza(x.texto_original)) for x in affs)
        achou_pais = any(x.pais_iso == e.get("pais_iso") for x in affs) if e.get("pais_iso") else True
        if achou_inst and achou_pais:
            ok_aff += 1
        elif affs:
            det.append(f"{e['nome'].split()[-1]}: inst={'ok' if achou_inst else (affs[0].instituicao or '?')[:40]} país={'ok' if achou_pais else affs[0].pais_iso}")
        else:
            det.append(f"{e['nome'].split()[-1]}: sem afiliação")
    if esperados and ok_aff == len(esperados):
        r["afiliacao"] = ("sim", f"{ok_aff} de {len(esperados)}")
    elif ok_aff > 0 or any("inst=ok" in d or "país=ok" in d for d in det):
        r["afiliacao"] = ("parcial", "; ".join(det))
    else:
        r["afiliacao"] = ("não", "; ".join(det) or "sem autores")
    # citacoes
    minimo = gab.get("citacoes_min", 0)
    n = len({(normaliza(c.autor), c.ano) for c in model.citacoes})
    if n >= minimo:
        r["citacoes"] = ("sim", f"{n} únicas (mín. {minimo})")
    elif n >= 0.5 * minimo:
        r["citacoes"] = ("parcial", f"{n} únicas (mín. {minimo})")
    else:
        r["citacoes"] = ("não", f"{n} únicas (mín. {minimo})")
    # referencias
    esp = gab.get("referencias")
    n = len(model.referencias)
    if esp:
        dif = abs(n - esp)
        if dif <= max(1, round(0.05 * esp)):
            r["referencias"] = ("sim", f"{n} de {esp} · {model.estilo_referencias}")
        elif dif <= round(0.2 * esp):
            r["referencias"] = ("parcial", f"{n} de {esp} · {model.estilo_referencias}")
        else:
            r["referencias"] = ("não", f"{n} de {esp}")
    else:
        r["referencias"] = ("?", f"{n}")
    # extras informativos
    ex = []
    if gab.get("doi"):
        ex.append("DOI ok" if model.doi == gab["doi"] else f"DOI {model.doi}")
    for k in ("recebido", "aceito"):
        if (gab.get("datas") or {}).get(k):
            v = getattr(model.datas, k)
            ex.append(f"{k} {'ok' if v == gab['datas'][k] else (v or 'faltou')}")
    if gab.get("resumos"):
        langs = [x.idioma for x in model.resumos]
        ex.append("resumos ok" if sorted(langs) == sorted(gab["resumos"]) else f"resumos {langs}")
    if gab.get("idioma"):
        ex.append("idioma ok" if model.idioma == gab["idioma"] else f"idioma {model.idioma}")
    r["_extras"] = "; ".join(ex)
    return r


def tabela(resultados: dict) -> str:
    cab = "| Arquivo | " + " | ".join(ROTULOS[e] for e in ELEMENTOS) + " | Extras |"
    sep = "|---|" + "---|" * (len(ELEMENTOS) + 1)
    linhas = [cab, sep]
    for nome, r in resultados.items():
        cels = []
        for e in ELEMENTOS:
            v, d = r[e]
            cels.append(f"**{v}**" if v in ("sim", "não", "parcial") else v)
        linhas.append(f"| {nome} | " + " | ".join(cels) + f" | {r.get('_extras', '')} |")
    detalhes = ["", "Detalhes:"]
    for nome, r in resultados.items():
        for e in ELEMENTOS:
            v, d = r[e]
            if v != "sim":
                detalhes.append(f"- {nome} · {ROTULOS[e]}: {v} — {d}")
    return "\n".join(linhas + detalhes)
