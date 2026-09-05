"""
Tabelas e equacoes do PDF.

Tabelas (duas passadas):
  1. `page.find_tables()` padrao, que acha grades com linhas verticais e horizontais (layout de revista de saude);
  2. para cada legenda "Tabela N" que sobrou sem grade, uma segunda passada restrita a regiao abaixo (e depois acima)
     da legenda, com `horizontal_strategy="lines", vertical_strategy="text"`, que e o que reconhece tabelas no estilo
     booktabs (so filetes horizontais), comum em revistas feitas em LaTeX.
As linhas de texto que caem dentro da bbox de uma tabela saem do fluxo do corpo (zona "tabela"), senao virariam
paragrafos soltos no meio do artigo.

Equacoes: PDF nao guarda MathML. O que da para fazer sem inventar e recortar a regiao da equacao como imagem de alta
resolucao e emiti-la em <disp-formula><graphic/>, que e o que a SPS aceita quando nao ha MathML. Sao reconhecidas:
  a) equacoes numeradas: uma linha cujo texto e so "(12)" (ou "(12a)"); a equacao sao as demais linhas do mesmo bloco
     do PDF, que e como geradores de PDF (LaTeX, Word) agrupam formula e numero;
  b) equacoes destacadas sem numero: bloco isolado com fonte matematica dominante.
As linhas usadas saem do fluxo do corpo (zona "equacao").

Nada e inventado: o texto bruto vai junto (para o operador conferir), mas o XML leva a imagem e um aviso pedindo o
MathML quando houver o original em DOCX ou LaTeX.
"""
import re
from collections import defaultdict
from typing import Dict, List, Optional

RE_NUM_EQ = re.compile(r"^\(\s*(\d{1,3}[a-zA-Z]?(?:\.\d{1,3})?)\s*\)$")
RE_LEGENDA_TAB = re.compile(r"^\s*(Tabela|Table|Quadro|Cuadro)\s*(\d+)\b", re.I)
# fontes tipicas de matematica em PDF (LaTeX, Word, InDesign)
RE_FONTE_MAT = re.compile(r"(math|cmmi|cmsy|cmex|msam|msbm|symbol|mtmi|mtsy|euclid|cambriamath|stix|xits|asana)", re.I)
MIN_LINHAS = 2
MIN_COLUNAS = 2


def _limpa(t):
    return re.sub(r"\s+", " ", (t or "").replace("\n", " ")).strip()


def _centro_dentro(bbox, ln, folga=2.0):
    bx0, by0, bx1, by1 = bbox
    cx, cy = (ln.x0 + ln.x1) / 2, (ln.y0 + ln.y1) / 2
    return bx0 - folga <= cx <= bx1 + folga and by0 - folga <= cy <= by1 + folga


def _valida(celulas) -> bool:
    if len(celulas) < MIN_LINHAS or max((len(l) for l in celulas), default=0) < MIN_COLUNAS:
        return False
    preenchidas = sum(1 for l in celulas for c in l if c)
    return preenchidas >= 4


def _extrai(t):
    try:
        celulas = [[_limpa(c) for c in linha] for linha in t.extract()]
    except Exception:  # noqa: BLE001
        return None
    if not _valida(celulas):
        return None
    n_cab = 0
    try:
        if t.header is not None and not t.header.external:
            n_cab = 1
    except Exception:  # noqa: BLE001
        n_cab = 0
    return {"bbox": [round(v, 1) for v in t.bbox], "celulas": celulas, "linhas_cabecalho": n_cab,
            "colunas": max(len(l) for l in celulas), "qualidade": "alta"}


RE_DOIS_NUMEROS = re.compile(r"\d[\d.,]*\s+[-−]?\d")


def avalia_grade(celulas) -> str:
    """Grade reconstruida sem linhas verticais pode embaralhar colunas ("1 ,78 4306" numa celula so).
    Devolve 'media' quando a reconstrucao parece boa e 'baixa' quando ha sinal de colunas grudadas."""
    corpo = [l for l in celulas[1:] if any(l)]
    if not corpo:
        return "baixa"
    suspeitas = sum(1 for l in corpo for c in l if c and RE_DOIS_NUMEROS.search(c))
    total = sum(1 for l in corpo for c in l if c)
    return "baixa" if total and suspeitas / total > 0.25 else "media"


def _marca_zona(paginas, pno, bbox):
    for ln in paginas.get(pno, []):
        if ln.zona in ("corpo", "nota") and _centro_dentro(bbox, ln):
            ln.zona = "tabela"


def _legenda_perto(bbox, legendas, folga_acima=90.0, folga_abaixo=60.0):
    """Legenda 'Tabela N' logo acima (mais comum) ou logo abaixo da grade, com sobreposicao horizontal."""
    bx0, by0, bx1, by1 = bbox
    melhor, dist = None, None
    for leg in legendas:
        sobre = min(bx1, leg.x1) - max(bx0, leg.x0)
        if sobre <= 0.15 * max(bx1 - bx0, 1):
            continue
        if by0 - folga_acima <= leg.y1 <= by0 + 6:
            d = by0 - leg.y1
        elif by1 - 6 <= leg.y0 <= by1 + folga_abaixo:
            d = leg.y0 - by1
        else:
            continue
        if dist is None or d < dist:
            melhor, dist = leg, d
    return melhor


def detecta_tabelas(pdf, paginas: Dict[int, list], altura_pagina: float) -> List[dict]:
    """Devolve [{pagina, bbox, celulas, linhas_cabecalho, colunas}] e tira do corpo as linhas internas.
    Uma grade so e aceita como tabela quando tem legenda "Tabela N" perto: PDFs de revista costumam ter caixas e
    filetes de diagramacao que o detector de grade confunde com tabela, e engoli-los apagaria texto do artigo."""
    import pymupdf
    achadas = []
    for pno, page in enumerate(pdf, start=1):
        da_pagina = []
        legendas = [ln for ln in paginas.get(pno, []) if ln.zona in ("corpo", "nota") and RE_LEGENDA_TAB.match(ln.texto)]
        try:
            tf = page.find_tables()
            for t in getattr(tf, "tables", []):
                g = _extrai(t)
                if not g:
                    continue
                leg = _legenda_perto(g["bbox"], legendas)
                if leg is None:
                    continue  # caixa de diagramacao, nao tabela
                g["pagina"] = pno
                g["legenda_y"] = leg.y0
                da_pagina.append(g)
        except Exception:  # noqa: BLE001
            pass
        # segunda passada: legendas ainda sem grade (tabelas booktabs)
        for leg in legendas:
            if any(_centro_dentro(g["bbox"], leg, folga=6) for g in da_pagina):
                continue
            if any(g["bbox"][1] - 40 <= leg.y1 <= g["bbox"][3] + 40 and
                   g["bbox"][0] - 10 <= leg.x0 <= g["bbox"][2] + 10 for g in da_pagina):
                continue  # ja existe grade colada nesta legenda
            # limites da coluna: da propria legenda, com folga
            x0, x1 = leg.x0 - 6, max(leg.x1, leg.x0 + 120) + 6
            outras_y = sorted(o.y0 for o in legendas if o is not leg and abs(o.x0 - leg.x0) < 40 and o.y0 > leg.y1)
            teto_baixo = min(outras_y) - 4 if outras_y else altura_pagina * 0.96
            for clip in (pymupdf.Rect(x0, leg.y1 + 1, x1, teto_baixo),
                         pymupdf.Rect(x0, max(altura_pagina * 0.03, leg.y0 - 420), x1, leg.y0 - 1)):
                if clip.height < 20 or clip.width < 40:
                    continue
                try:
                    tf2 = page.find_tables(clip=clip, horizontal_strategy="lines", vertical_strategy="text")
                except Exception:  # noqa: BLE001
                    continue
                grades = [g for g in (_extrai(t) for t in getattr(tf2, "tables", [])) if g]
                if not grades:
                    continue
                g = max(grades, key=lambda g: len(g["celulas"]) * g["colunas"])
                g["qualidade"] = avalia_grade(g["celulas"])
                g["pagina"] = pno
                g["legenda_y"] = leg.y0
                da_pagina.append(g)
                break
        for g in da_pagina:
            _marca_zona(paginas, pno, g["bbox"])
        achadas.extend(da_pagina)
    achadas.sort(key=lambda g: (g["pagina"], g["bbox"][1]))
    return achadas


def _eh_matematica(linha) -> bool:
    return bool(RE_FONTE_MAT.search(linha.font or ""))


def _parece_texto_corrido(texto: str) -> bool:
    palavras = re.findall(r"[A-Za-zÀ-ú]{3,}", texto)
    return len(palavras) >= 8 and texto.rstrip().endswith((".", ";", ":"))


def detecta_equacoes(paginas: Dict[int, list], corpo_size: float) -> List[dict]:
    """Devolve [{pagina, bbox, rotulo, texto, numerada}] e marca as linhas usadas como zona 'equacao'."""
    achadas = []
    for pno, linhas in paginas.items():
        livres = [ln for ln in linhas if ln.zona == "corpo" and not ln.rotacionada]
        por_bloco = defaultdict(list)
        for ln in livres:
            por_bloco[ln.bloco].append(ln)
        usadas = set()
        # (a) numeradas: o numero "(N)" e uma linha do bloco; a equacao sao as outras linhas do mesmo bloco
        for bloco, lns in sorted(por_bloco.items()):
            num = next((o for o in lns if RE_NUM_EQ.match(o.texto.strip())), None)
            if num is None:
                continue
            corpo_eq = [o for o in lns if o is not num]
            if not corpo_eq:
                # numero sozinho no bloco: vira candidato "so numero", que a fusao cola na formula vizinha
                num.zona = "equacao"
                usadas.add(id(num))
                m0 = RE_NUM_EQ.match(num.texto.strip())
                achadas.append({"pagina": pno, "rotulo": m0.group(1), "numerada": True, "texto": "", "so_numero": True,
                                "bbox": [round(num.x0, 1), round(num.y0, 1), round(num.x1, 1), round(num.y1, 1)]})
                continue
            texto = " ".join(o.texto for o in sorted(corpo_eq, key=lambda o: (o.y0, o.x0))).strip()
            if _parece_texto_corrido(texto):
                continue  # paragrafo que por acaso termina com "(3)"
            tem_mat = any(_eh_matematica(o) for o in corpo_eq)
            if not (tem_mat or re.search(r"[=+\-−×·/^_∑∫√≈≤≥≠∂πα-ω]", texto)):
                continue
            grupo = corpo_eq + [num]
            for o in grupo:
                usadas.add(id(o))
                o.zona = "equacao"
            m = RE_NUM_EQ.match(num.texto.strip())
            achadas.append({"pagina": pno, "rotulo": m.group(1), "numerada": True, "texto": _limpa(texto),
                            "bbox": [round(min(o.x0 for o in grupo), 1), round(min(o.y0 for o in grupo), 1),
                                     round(max(o.x1 for o in grupo), 1), round(max(o.y1 for o in grupo), 1)]})
        # (b) sem numero: bloco isolado com fonte matematica dominante
        for bloco, lns in sorted(por_bloco.items()):
            if any(id(o) in usadas for o in lns):
                continue
            mat = [o for o in lns if _eh_matematica(o)]
            texto = " ".join(o.texto for o in sorted(lns, key=lambda o: (o.y0, o.x0))).strip()
            if not mat or len(mat) < max(1, len(lns) // 2) or len(texto) > 200 or _parece_texto_corrido(texto):
                continue
            for o in lns:
                usadas.add(id(o))
                o.zona = "equacao"
            achadas.append({"pagina": pno, "rotulo": None, "numerada": False, "texto": _limpa(texto),
                            "bbox": [round(min(o.x0 for o in lns), 1), round(min(o.y0 for o in lns), 1),
                                     round(max(o.x1 for o in lns), 1), round(max(o.y1 for o in lns), 1)]})
    achadas.sort(key=lambda e: (e["pagina"], e["bbox"][1]))
    return _funde(achadas)


def _pode_juntar(a: dict, b: dict) -> bool:
    """Duas equacoes que ja tem numero proprio sao equacoes diferentes, ainda que coladas."""
    return not (a.get("rotulo") and b.get("rotulo") and a["rotulo"] != b["rotulo"])


def _junta(a: dict, b: dict) -> dict:
    x0, y0, x1, y1 = a["bbox"]
    bx0, by0, bx1, by1 = b["bbox"]
    a["bbox"] = [min(x0, bx0), min(y0, by0), max(x1, bx1), max(y1, by1)]
    a["texto"] = " ".join(t for t in (a["texto"], b["texto"]) if t).strip()
    if b.get("numerada") and not a.get("rotulo"):
        a["numerada"], a["rotulo"] = True, b["rotulo"]
    a["so_numero"] = a.get("so_numero", False) and b.get("so_numero", False)
    return a


def _funde(cands: List[dict], gap_v: float = 12.0, gap_h: float = 140.0) -> List[dict]:
    """Geradores de PDF quebram uma formula em varios blocos (numerador, denominador, e o numero da equacao, que pode
    ficar sozinho a direita). Blocos vizinhos na mesma coluna sao a mesma equacao: viram um so recorte.
    Duas passadas ate estabilizar: colados na horizontal (formula + numero) e empilhados na vertical (fracoes)."""
    itens = [dict(c) for c in cands]
    for _ in range(3):
        mudou = False
        # horizontal: mesma faixa vertical, um ao lado do outro
        itens.sort(key=lambda e: (e["pagina"], e["bbox"][1], e["bbox"][0]))
        out: List[dict] = []
        for c in itens:
            alvo = None
            for a in out:
                if a["pagina"] != c["pagina"]:
                    continue
                alt = min(a["bbox"][3] - a["bbox"][1], c["bbox"][3] - c["bbox"][1]) or 1
                sobre_v = min(a["bbox"][3], c["bbox"][3]) - max(a["bbox"][1], c["bbox"][1])
                gap = max(c["bbox"][0] - a["bbox"][2], a["bbox"][0] - c["bbox"][2])
                if sobre_v > 0.5 * alt and gap <= gap_h and _pode_juntar(a, c):
                    alvo = a
                    break
            if alvo is not None:
                _junta(alvo, c)
                mudou = True
            else:
                out.append(c)
        itens = out
        # vertical: empilhados na mesma coluna
        itens.sort(key=lambda e: (e["pagina"], e["bbox"][1]))
        out = []
        for c in itens:
            if out:
                a = out[-1]
                larg = min(a["bbox"][2] - a["bbox"][0], c["bbox"][2] - c["bbox"][0]) or 1
                sobre_h = min(a["bbox"][2], c["bbox"][2]) - max(a["bbox"][0], c["bbox"][0])
                if (a["pagina"] == c["pagina"] and c["bbox"][1] - a["bbox"][3] <= gap_v and sobre_h > 0.3 * larg
                        and _pode_juntar(a, c)):
                    _junta(a, c)
                    mudou = True
                    continue
            out.append(c)
        itens = out
        if not mudou:
            break
    # descarta restos: numero sem formula, ou pedaco sem numero, curto e sem operador
    return [e for e in itens if not e.get("so_numero") and
            (e["numerada"] or (len(e["texto"]) >= 3 and re.search(r"[=+\-−×·/^_∑∫√≈≤≥≠∂]", e["texto"])))]


def recorta(pdf, pagina: int, bbox, zoom: float = 4.0, folga: float = 3.0):
    """Recorta a regiao da pagina como PNG de alta resolucao (para <graphic> de equacao)."""
    import pymupdf
    page = pdf[pagina - 1]
    r = pymupdf.Rect(bbox[0] - folga, bbox[1] - folga, bbox[2] + folga, bbox[3] + folga) & page.rect
    if r.is_empty or r.width < 4 or r.height < 4:
        return None, None, None
    pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), clip=r, alpha=False)
    return pix.tobytes("png"), pix.width, pix.height
