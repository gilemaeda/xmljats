"""Corpo: secoes, paragrafos, citacoes autor-data, notas de rodape, figuras/tabelas, back matter."""
import re
from typing import List, Optional

from .leitura import Documento, Paragrafo
from .modelo import ArticleModel, Secao, Citacao, Nota, Figura, Tabela, Equacao
from .util import RE_MARCADOR, RE_CHAMADA_NOTA, SUPERSCRITOS, normaliza, marcador_normalizado, limpa_chamadas

RE_NUM = re.compile(r"^\s*(\d+(?:\.\d+)*)\.?\s+(\S.*)$")
RE_FIG = re.compile(r"^\s*(Figura|Figure|Fig\.|Tabela|Table|Quadro|Gr[aá]fico|Imagem|Ilustra[çc][ãa]o)\s*(\d+)\s*[-–:.]?\s*(.*)$", re.I)
RE_FONTE = re.compile(r"^\s*(Fonte|Source|Fuente)\s*[:.]\s*(.*)$", re.I)
INTRO = {"introducao", "introduction", "introduccion", "apresentacao", "consideracoes iniciais", "notas introdutorias", "preliminares", "introito"}
SEC_TYPES = [
    ("intro", r"introdu|introduction|introducci|apresenta|considera[cç][oõ]es iniciais"),
    ("methods", r"metodolog|method|m[eé]todos?|materiais? e m[eé]todos|procedimentos metodol"),
    ("results", r"resultados?|results?|achados"),
    ("discussion", r"discuss"),
    ("conclusions", r"conclus|considera[cç][oõ]es finais|final remarks|concluding|notas finais|palavras finais"),
    ("cases", r"estudo de caso|case study|caso"),
]
KW_BACK = re.compile(
    r"^(authorship information|informa[çc][õo]es? (sobre|dos?|das?) autor\w*|sobre (os|as|o|a) autor\w*|dados d[oa]s? autor\w*|about the authors?|"
    r"additional information|declara[çc][õo]es|declaration|editorial process|how to cite|como citar|c[óo]mo citar|editorial team|"
    r"agradecimentos?|acknowledg|financiamento|funding|conflito de interesse|conflict of interest|anexos?|ap[êe]ndices?|appendix|notas?|notes|"
    r"nota de coautoria|nota dos autores|contribui[çc][ãa]o dos autores|author contributions?|credit)\b",
    re.I,
)
RE_CIT_PAREN = re.compile(r"\(([^()]{3,260})\)")
RE_CIT_ITEM = re.compile(
    r"^(?:cf\.?\s*|ver\s+|vide\s+|see\s+|v\.\s*|apud\s+|conforme\s+|segundo\s+)?"
    r"([A-ZÀ-Ú][\wÀ-ú'’\-]+(?:\s+(?:e|and|&|y|;)\s+[A-ZÀ-Ú][\wÀ-ú'’\-]+)*(?:\s+et\s+al\.?)?),?\s+"
    r"(\d{4}[a-z]?)(?:\s*[,;]?\s*(?:p|pp|págs?|pgs?)\.?\s*[\d\-–, ]+)?\.?$"
)
RE_CIT_FALLBACK = re.compile(r"([A-ZÀ-Ú][\wÀ-ú'’\-]+)(?:\s+et\s+al\.?)?,?\s+(\d{4}[a-z]?)(?=[,;\s.)]|$)")
RE_CIT_NARR = re.compile(r"\b([A-ZÀ-Ú][\wÀ-ú'’\-]+(?:\s+(?:e|and|y)\s+[A-ZÀ-Ú][\wÀ-ú'’\-]+)?)\s+\((\d{4}[a-z]?)(?:,\s*(?:p|pp)\.?\s*[\d\-–, ]+)?\)")
KW_TIPO_NOTA = [
    ("current-aff", r"(doutor|mestre|professor|pesquisador|graduad|bacharel|advogad|defensor|lattes|orcid)"),
    ("supported-by", r"(financiad|financiamento|apoio|bolsa|capes|cnpq|fapesp|fapemig|funding|supported by|resultante de (investiga|pesquisa))"),
    ("conflict", r"(conflito de interesse|conflict of interest)"),
    ("presented-at", r"(apresentad[oa] (no|na|em)|presented at|comunica[çc][ãa]o apresentada)"),
]
STOP_CIT = {"Art", "Arts", "Lei", "Decreto", "Emenda", "Constitui", "Súmula", "Resolução", "Portaria", "Inciso", "Parágrafo", "Vol", "Ano"}


def eh_titulo_secao(p: Paragrafo, doc: Documento, no_front=False) -> bool:
    t = p.texto.strip()
    if not (3 <= len(t) <= 130) or len(p.linhas) > 3:
        return False
    if t.rstrip().endswith((".", ";", ",", "”", "\"")) and not RE_NUM.match(t):
        return False
    if RE_FIG.match(t) or RE_FONTE.match(t) or re.match(r"^(resumo|abstract|resumen|palavras|keywords|palabras)", t, re.I):
        return False
    if re.search(r"\b(et al|p\.|pp\.|Disponível|https?://)\b", t) or re.search(r"\(\d{4}[a-z]?\)", t):
        return False
    if re.search(r"^\d+\s+\S+\.\s+\d+\s+\S+", t) or t.startswith(("Art.", "Arts.", "art.")):
        return False  # sumario "1 Introdução. 2 ..." ou citacao de lei
    for c in doc.cabecalhos:
        if normaliza(t) and normaliza(t) in normaliza(c):
            return False
    corpo = doc.corpo_size
    numerado = bool(RE_NUM.match(t)) and not re.match(r"^\d+\s+(de|do|da|a|o|e)\s", t)
    fonte_diferente = p.font != doc.corpo_font
    maior = p.size >= corpo * 1.12
    palavras = [w for w in re.findall(r"[A-Za-zÀ-ú]+", t) if len(w) > 2]
    caixa_titulo = bool(palavras) and (t.isupper() or sum(1 for w in palavras if w[0].isupper()) >= 0.6 * len(palavras))
    menor_destacada = (p.size <= corpo * 0.9 and fonte_diferente and not p.italic and len(p.linhas) == 1 and len(t) < 70
                       and t[:1].isupper() and (caixa_titulo or numerado))
    if p.bold and (numerado or len(t) < 90):
        return True
    if maior and len(t) < 110:
        return True
    if numerado and (fonte_diferente or abs(p.size - corpo) > 0.6 or p.italic):
        return True
    if menor_destacada and not no_front:
        return True
    return False


def indice_primeira_secao(doc: Documento) -> Optional[int]:
    """Primeiro titulo de secao do corpo (introducao ou '1 ...') nas primeiras paginas."""
    limite = min(len(doc.paragrafos), 400)
    for i, p in enumerate(doc.paragrafos[:limite]):
        if p.pagina > 5:
            break
        if not eh_titulo_secao(p, doc):
            continue
        t = p.texto.strip()
        m = RE_NUM.match(t)
        n = normaliza(m.group(2) if m else t)
        if n in INTRO or any(n.startswith(x) for x in INTRO):
            return i
        if m and m.group(1) in ("1", "1."):
            return i
    # fallback: primeiro titulo de secao apos o ultimo resumo/keywords
    for i, p in enumerate(doc.paragrafos[:limite]):
        if p.pagina >= 2 and eh_titulo_secao(p, doc) and not RE_FIG.match(p.texto):
            return i
    return None


def extrai_corpo(doc: Documento, model: ArticleModel, i_sec: Optional[int], i_ref: Optional[int]):
    if i_sec is None:
        model.aviso("Início do corpo não identificado (nenhum título de seção reconhecido).")
        return
    fim = i_ref if i_ref is not None else len(doc.paragrafos)
    atual: Optional[Secao] = None
    ultimo_par_texto = None
    for p in doc.paragrafos[i_sec:fim]:
        t = p.texto.strip()
        if not t:
            continue
        if eh_titulo_secao(p, doc):
            m = RE_NUM.match(t)
            numero = m.group(1).rstrip(".") if m else None
            titulo = m.group(2).strip() if m else t
            # titulo de secao em duas linhas: a anterior terminou em ':' ou '-' e ainda nao tem paragrafos
            if atual is not None and not atual.paragrafos and numero is None and atual.titulo.rstrip().endswith((":", "-", "–")):
                atual.titulo = (atual.titulo.rstrip() + " " + titulo).strip()
                atual.titulo_completo = ((atual.titulo_completo or "").rstrip() + " " + t).strip()
                continue
            nivel = numero.count(".") + 1 if numero else (1 if not model.secoes or atual is None or atual.nivel == 1 else atual.nivel)
            sec_type = next((st for st, rx in SEC_TYPES if re.search(rx, normaliza(titulo), re.I)), None)
            atual = Secao(titulo=titulo, nivel=nivel, numero=numero, sec_type=sec_type, pagina=p.pagina, titulo_completo=t)
            model.secoes.append(atual)
            ultimo_par_texto = None
            continue
        if atual is None:
            continue
        if (RE_FIG.match(t) and _eh_legenda(t)) or RE_FONTE.match(t):
            _registra_figura(model, p, t, doc, atual)
            continue
        # continuacao de paragrafo entre paginas; os paragrafos guardam as chamadas de nota como "[^n]"
        tm = (p.texto_marcado or t).strip()
        if atual.paragrafos and ultimo_par_texto is not None and not ultimo_par_texto.rstrip().endswith((".", "!", "?", ":", "”", "\"", ")")) and t[:1].islower():
            atual.paragrafos[-1] = (atual.paragrafos[-1] + " " + tm).strip()
        else:
            atual.paragrafos.append(tm)
        ultimo_par_texto = limpa_chamadas(atual.paragrafos[-1])
    if model.secoes:
        model.marca("secoes", "lido (negrito / tamanho / numeração / fonte diferente do corpo)")
    _citacoes(model)
    _notas(doc, model, i_sec, fim)
    _liga_tabelas(doc, model)
    _liga_equacoes(doc, model)
    _chamadas_figuras(model)
    _back_matter(doc, model, i_ref)


def _eh_legenda(t: str) -> bool:
    """Distingue legenda ("Tabela 1 Descrição da amostra...") de menção no texto ("Table 1 shows the sample...").
    Vale como legenda quando há separador depois do número, ou quando o texto seguinte não continua a frase."""
    m = RE_FIG.match(t)
    if not m:
        return False
    resto = (m.group(3) or "").strip()
    if not resto:
        return True
    entre = t[m.end(2):m.end(2) + 3]
    if re.match(r"\s*[-–—:.]", entre):  # "Tabela 1: ..." / "Figura 2 - ..."
        return True
    if resto[:1].islower():  # "Table 1 shows ..." é menção
        return False
    return len(t) <= 400


def _registra_figura(model: ArticleModel, p: Paragrafo, t: str, doc: Documento, atual: Secao):
    m = RE_FIG.match(t)
    if m:
        tipo = "table" if re.match(r"tabela|table|quadro", m.group(1), re.I) else "fig"
        if tipo == "table":
            # a grade vem do detector do PyMuPDF; aqui guardamos so a legenda e onde ela aparece
            model.tabelas.append(Tabela(numero=m.group(2), rotulo=f"{m.group(1)} {m.group(2)}", legenda=m.group(3).strip(" -:"),
                                        pagina=p.pagina, secao_indice=len(model.secoes) - 1, pos_paragrafo=len(atual.paragrafos)))
        f = Figura(tipo=tipo, rotulo=f"{m.group(1)} {m.group(2)}", legenda=m.group(3).strip(" -:"), pagina=p.pagina,
                   numero=m.group(2), secao_indice=len(model.secoes) - 1, pos_paragrafo=len(atual.paragrafos))
        if tipo == "fig":
            usados = {x.imagem_indice for x in model.figuras if x.imagem_indice is not None}
            cands = [(i, im) for i, im in enumerate(doc.imagens) if im["pagina"] == p.pagina and i not in usados]
            # a legenda costuma ficar logo abaixo da imagem; senao, a imagem mais proxima abaixo da legenda
            acima = [(p.y0 - im["bbox"][3], i) for i, im in cands if im["bbox"][3] <= p.y0 + 6]
            abaixo = [(im["bbox"][1] - p.y1, i) for i, im in cands if im["bbox"][1] >= p.y1 - 6]
            escolha = min(acima)[1] if acima else (min(abaixo)[1] if abaixo else None)
            if escolha is not None:
                im = doc.imagens[escolha]
                f.imagem_indice, f.ext, f.largura, f.altura = escolha, im["ext"], im["largura"], im["altura"]
        model.figuras.append(f)
        return
    m = RE_FONTE.match(t)
    if not m:
        return
    if model.tabelas and model.tabelas[-1].pagina == p.pagina and not model.tabelas[-1].fonte and (
            not model.figuras or model.figuras[-1].pagina != p.pagina):
        model.tabelas[-1].fonte = m.group(2).strip()
    elif model.figuras and model.figuras[-1].pagina == p.pagina and not model.figuras[-1].fonte:
        model.figuras[-1].fonte = m.group(2).strip()


def _liga_tabelas(doc, model: ArticleModel):
    """Casa cada legenda 'Tabela N' com a grade detectada na mesma pagina (a mais proxima abaixo da legenda, senao acima).
    Grades sem legenda entram como tabela sem rotulo, para o operador nomear na revisao."""
    livres = list(doc.tabelas)
    for t in model.tabelas:
        cands = [g for g in livres if g["pagina"] == t.pagina]
        if not cands:
            cands = [g for g in livres if abs(g["pagina"] - t.pagina) <= 1]
        if not cands:
            continue
        g = min(cands, key=lambda g: g["bbox"][1])
        livres.remove(g)
        t.celulas, t.linhas_cabecalho, t.colunas, t.bbox = g["celulas"], g["linhas_cabecalho"], g["colunas"], g["bbox"]
        t.qualidade = g.get("qualidade", "alta")
    for g in livres:
        model.tabelas.append(Tabela(numero=None, rotulo="", legenda="", pagina=g["pagina"], celulas=g["celulas"],
                                    linhas_cabecalho=g["linhas_cabecalho"], colunas=g["colunas"], bbox=g["bbox"],
                                    qualidade=g.get("qualidade", "alta")))
    model.tabelas.sort(key=lambda t: (t.pagina, t.bbox[1] if t.bbox else 0))
    sem_grade = [t.rotulo for t in model.tabelas if not t.celulas]
    if sem_grade:
        model.aviso(f"Legenda(s) de tabela sem grade reconhecida no PDF: {', '.join(sem_grade)} (T01).")
    incertas = [t.rotulo or "(sem rótulo)" for t in model.tabelas if t.celulas and t.qualidade == "baixa"]
    if incertas:
        model.aviso(f"Tabela(s) sem linhas verticais no PDF cujas colunas não foram reconstruídas com segurança "
                    f"({', '.join(incertas)}); vão para o XML como imagem (T02).")
    sem_legenda = sum(1 for t in model.tabelas if t.celulas and not t.rotulo)
    if sem_legenda:
        model.aviso(f"{sem_legenda} tabela(s) sem legenda 'Tabela N' no PDF; rotule na revisão (T01).")
    if model.tabelas:
        model.marca("tabelas", "lido (grade do PDF + legenda)")
    texto = " ".join(par for s in model.secoes for par in s.paragrafos)
    for t in model.tabelas:
        if t.numero and re.search(r"\b(Tabela|Table|Quadro)s?\.?\s*" + re.escape(t.numero) + r"(?!\d)", texto, re.I):
            t.chamada_no_texto = True


def _liga_equacoes(doc, model: ArticleModel):
    """Cada equacao detectada vira Equacao, posicionada na secao/paragrafo em que aparece."""
    if not doc.equacoes:
        return
    # posicao: usa a ultima secao/paragrafo cuja pagina e <= a da equacao
    pos_por_pagina = {}
    for si, sec in enumerate(model.secoes):
        pos_por_pagina.setdefault(sec.pagina, (si, len(sec.paragrafos)))
    for eq in doc.equacoes:
        si, pp = None, None
        for si_c, sec in enumerate(model.secoes):
            if sec.pagina <= eq["pagina"]:
                si, pp = si_c, len(sec.paragrafos)
        model.equacoes.append(Equacao(numero=eq.get("rotulo"), rotulo=(f"({eq['rotulo']})" if eq.get("rotulo") else None),
                                      texto=eq.get("texto") or "", pagina=eq["pagina"], numerada=bool(eq.get("numerada")),
                                      secao_indice=si, pos_paragrafo=pp, largura=eq.get("largura"), altura=eq.get("altura"),
                                      bbox=eq.get("bbox") or []))
    model.marca("equacoes", "lido (número entre parênteses / fonte matemática); recortadas como imagem")
    texto = " ".join(par for s in model.secoes for par in s.paragrafos)
    for e in model.equacoes:
        if e.numero and re.search(r"(equa[çc][ãa]o|equation|eq\.?|f[óo]rmula)\s*\(?" + re.escape(e.numero) + r"\)?(?!\d)", texto, re.I):
            e.chamada_no_texto = True
    n_img = sum(1 for e in model.equacoes if e.largura)
    if model.equacoes:
        model.aviso(f"{len(model.equacoes)} equação(ões) destacada(s) recortada(s) do PDF como imagem ({n_img} com recorte); "
                    f"o PDF não guarda MathML, então o XML leva a imagem — para MathML é preciso o DOCX ou o LaTeX original (E01).")


def _chamadas_figuras(model: ArticleModel):
    texto = " ".join(par for s in model.secoes for par in s.paragrafos)
    for f in model.figuras:
        rot = re.escape(f.rotulo.split()[0][:3]) + r"\w*\.?\s*" + re.escape(f.rotulo.split()[-1]) + r"(?!\d)"
        if re.search(rot, texto, re.I):
            f.chamada_no_texto = True
    sem_imagem = [f.rotulo for f in model.figuras if f.tipo == "fig" and f.imagem_indice is None]
    if sem_imagem:
        model.aviso(f"Legenda(s) sem imagem associada no PDF: {', '.join(sem_imagem)} (F01).")


def _citacoes(model: ArticleModel):
    vistas = set()
    for s in model.secoes:
        for par in s.paragrafos:
            for m in RE_CIT_PAREN.finditer(par):
                for item in re.split(r";\s*", m.group(1)):
                    item = item.strip()
                    mi = RE_CIT_ITEM.match(item)
                    if not mi:
                        mf = list(RE_CIT_FALLBACK.finditer(item))
                        mi = mf[-1] if mf else None
                    if not mi:
                        continue
                    autor, ano = mi.group(1), mi.group(2)
                    if autor.split()[0] in STOP_CIT or autor.lower() in ("in", "art"):
                        continue
                    chave = (normaliza(autor), ano)
                    model.citacoes.append(Citacao(autor=autor, ano=ano, texto=item))
                    vistas.add(chave)
            for m in RE_CIT_NARR.finditer(par):
                autor, ano = m.group(1), m.group(2)
                if autor.split()[0] in STOP_CIT:
                    continue
                model.citacoes.append(Citacao(autor=autor, ano=ano, texto=m.group(0)))
    if model.citacoes:
        model.marca("citacoes", "lido (padrões (AUTOR, ano) e Autor (ano))")


def _notas(doc: Documento, model: ArticleModel, i_sec, fim):
    # chamadas no texto: sobrescritos numericos nas linhas do corpo + caracteres unicode
    chamadas = set()
    for sec in model.secoes:
        for par in sec.paragrafos:
            chamadas.update(RE_CHAMADA_NOTA.findall(par))
    for p in doc.paragrafos:
        for s in p.sups:
            s2 = marcador_normalizado(s)
            if s2:
                chamadas.add(s2)
        for ch in re.findall(r"[¹²³⁰-⁹]+", p.texto):
            chamadas.add("".join(SUPERSCRITOS[c] for c in ch))
    bios = {n_id for a in model.autores for n_id in []}
    for k, n in enumerate(doc.notas, start=1):
        l0 = n.linhas[0]
        rot = marcador_normalizado(l0.sup_inicio) if l0.sup_inicio else ""
        texto = n.texto
        if not rot:
            m = RE_MARCADOR.match(texto)
            if m:
                rot, texto = marcador_normalizado(m.group(1)), texto[m.end():].strip()
        tipo = "other"
        ligada = None
        for a_i, a in enumerate(model.autores, start=1):
            if rot and rot in a.marcadores and n.pagina <= 2:
                ligada = f"autor:{a_i}"
        if not ligada and "titulo_nota" in model.proveniencia and rot and rot in model.proveniencia["titulo_nota"]:
            ligada = "titulo"
        for tp, rx in KW_TIPO_NOTA:
            if re.search(rx, texto, re.I):
                tipo = tp
                break
        if ligada and ligada.startswith("autor") and tipo in ("other", "current-aff"):
            tipo = "current-aff"
        elif tipo == "current-aff":
            tipo = "other"  # biografia so e biografia quando ligada a um autor
        model.notas.append(Nota(id=f"fn{k}", rotulo=rot or str(k), texto=texto, pagina=n.pagina, tipo=tipo, chamada_no_texto=(rot in chamadas) if rot else False, ligada_a=ligada))
    if model.notas:
        model.marca("notas", "lido (zona de rodapé por tamanho de fonte + marcador)")


def _back_matter(doc: Documento, model: ArticleModel, i_ref):
    if i_ref is None:
        return
    atual = None
    for p in doc.paragrafos[i_ref + 1:]:
        t = p.texto.strip()
        t0 = p.linhas[0].texto.strip()
        if KW_BACK.match(t0) and len(t0) < 80:
            atual = {"titulo": t0, "texto": t[len(t0):].strip(), "pagina": p.pagina}
            model.back_matter.append(atual)
            continue
        if atual is not None:
            atual["texto"] = (atual["texto"] + " " + t).strip()
