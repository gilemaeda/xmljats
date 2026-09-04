"""
PoC - caracterizacao de PDFs de artigos para o pipeline XML-JATS.

Para cada PDF gera:
  poc/saida/<nome>.json  -> estrutura detectada (fontes, colunas, front matter, secoes, notas, referencias, figuras)
  poc/saida/<nome>.txt   -> dump do texto por pagina, com tamanho de fonte e negrito por linha (para inspecao)
e imprime um resumo em Markdown no stdout.

Uso:  python poc/analisa_pdf.py modelos/*.pdf article.segmented.pdf
"""
import glob
import json
import os
import re
import statistics
import sys
from collections import Counter, defaultdict

import fitz  # PyMuPDF

RE_DOI = re.compile(r"10\.\d{4,9}/[^\s\"<>]+")
RE_ISSN = re.compile(r"\b\d{4}-\d{3}[\dXx]\b")
RE_ORCID = re.compile(r"\b\d{4}-\d{4}-\d{4}-\d{3}[\dXx]\b")
RE_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
RE_NUMBERED_HEADING = re.compile(r"^\s*(\d+(?:\.\d+)*)\.?\s+\S")
RE_DATE_HINT = re.compile(
    r"(recebid[oa]|aceit[oa]|aprovad[oa]|publicad[oa]|received|accepted|published|recibido|aceptado)",
    re.I,
)
RE_FIG = re.compile(r"^\s*(Figura|Figure|Fig\.|Tabela|Table|Quadro|Gr[aá]fico|Imagem)\s*\d+", re.I)
RE_REF_ENTRY = re.compile(r"^[A-ZÀ-Ú][A-ZÀ-Ú'’\-]+(?:\s+[A-ZÀ-Ú][A-ZÀ-Ú'’\-]+)*,\s")  # SOBRENOME, Nome
RE_CITATION = re.compile(r"\(([A-ZÀ-Ú][A-Za-zÀ-ú'’\-]+(?:\s+(?:e|and|&|;)\s+[A-ZÀ-Ú][A-Za-zÀ-ú'’\-]+)*),?\s+(\d{4}[a-z]?)(?:,\s*p\.?\s*[\d\-–]+)?\)")

MARKERS = {
    "resumo": re.compile(r"^\s*(resumo|abstract|resumen|riassunto|résumé|zusammenfassung)\s*[:.]?\s*$", re.I),
    "palavras": re.compile(r"^\s*(palavras[- ]chave|keywords|key[- ]words|palabras[- ]clave|parole chiave|mots[- ]clés)\s*[:.]?", re.I),
    "referencias": re.compile(r"^\s*(refer[êe]ncias(\s+bibliogr[áa]ficas)?|references|bibliografia|bibliography|referencias)\s*$", re.I),
    "introducao": re.compile(r"^\s*(\d+\.?\s*)?(introdu[çc][ãa]o|introduction|introducción)\s*$", re.I),
    "conclusao": re.compile(r"^\s*(\d+\.?\s*)?(conclus[ãa]o|conclus[õo]es|considera[çc][õo]es finais|conclusion[s]?|final remarks|conclusiones)\s*$", re.I),
    "notas": re.compile(r"^\s*(notas|notes)\s*$", re.I),
    "sobre_autores": re.compile(r"^\s*(sobre (os|as) autor|dados d[oa]s? autor|about the author|informa[çc][õo]es sobre)", re.I),
}


def span_is_bold(span):
    return bool(span["flags"] & 16) or "bold" in span["font"].lower() or "black" in span["font"].lower()


def span_is_italic(span):
    return bool(span["flags"] & 2) or "italic" in span["font"].lower() or "oblique" in span["font"].lower()


def page_lines(page):
    """Linhas com texto, tamanho dominante, negrito, bbox e superscritos."""
    d = page.get_text("dict")
    out = []
    for b in d["blocks"]:
        if b["type"] != 0:
            continue
        for ln in b["lines"]:
            spans = [s for s in ln["spans"] if s["text"].strip()]
            if not spans:
                continue
            text = "".join(s["text"] for s in ln["spans"]).strip()
            sizes = Counter()
            bold_chars = 0
            ital_chars = 0
            total = 0
            sup = []
            for s in spans:
                n = len(s["text"].strip())
                sizes[round(s["size"], 1)] += n
                total += n
                if span_is_bold(s):
                    bold_chars += n
                if span_is_italic(s):
                    ital_chars += n
                if s["flags"] & 1:
                    sup.append(s["text"].strip())
            size = sizes.most_common(1)[0][0]
            out.append(
                {
                    "text": text,
                    "size": size,
                    "bold": bold_chars / max(total, 1) > 0.6,
                    "italic": ital_chars / max(total, 1) > 0.6,
                    "bbox": [round(v, 1) for v in ln["bbox"]],
                    "block_bbox": [round(v, 1) for v in b["bbox"]],
                    "sup": sup,
                    "font": spans[0]["font"],
                }
            )
    return out


def detect_columns(lines, page_width):
    """Conta linhas cujo bloco comeca na metade esquerda vs direita e e estreito."""
    narrow_left = narrow_right = wide = 0
    for ln in lines:
        x0, _, x1, _ = ln["block_bbox"]
        w = x1 - x0
        if w < page_width * 0.55:
            if x0 < page_width * 0.45:
                narrow_left += 1
            else:
                narrow_right += 1
        else:
            wide += 1
    n = max(narrow_left + narrow_right + wide, 1)
    if narrow_right / n > 0.25 and narrow_left / n > 0.25:
        return "duas colunas"
    return "uma coluna"


def analyse(path):
    doc = fitz.open(path)
    name = os.path.splitext(os.path.basename(path))[0]
    res = {
        "arquivo": os.path.basename(path),
        "paginas": doc.page_count,
        "metadata": {k: v for k, v in doc.metadata.items() if v},
        "tamanho_pagina_pt": [round(doc[0].rect.width), round(doc[0].rect.height)],
        "anexos_embutidos": doc.embfile_names() if doc.embfile_count() else [],
    }

    all_lines = []  # (page_no, line)
    chars_per_page = []
    images_per_page = []
    annots = []
    drawings_rects = 0
    for pno, page in enumerate(doc, start=1):
        lines = page_lines(page)
        all_lines.extend((pno, ln) for ln in lines)
        chars_per_page.append(sum(len(ln["text"]) for ln in lines))
        images_per_page.append(len(page.get_images(full=True)))
        for a in page.annots() or []:
            info = a.info
            annots.append(
                {
                    "pagina": pno,
                    "tipo": a.type[1],
                    "rect": [round(v, 1) for v in a.rect],
                    "conteudo": (info.get("content") or "")[:200],
                    "titulo": info.get("title") or "",
                    "assunto": info.get("subject") or "",
                    "cor": a.colors.get("stroke"),
                }
            )
        try:
            for dr in page.get_drawings():
                if dr.get("rect") and dr["rect"].width > 20 and dr["rect"].height > 8 and not dr.get("fill"):
                    drawings_rects += 1
        except Exception:
            pass

    res["texto_extraivel"] = sum(chars_per_page) > 200 * doc.page_count
    res["chars_por_pagina"] = chars_per_page
    res["imagens_por_pagina"] = images_per_page
    res["anotacoes"] = annots[:60]
    res["total_anotacoes"] = len(annots)
    res["retangulos_desenhados"] = drawings_rects

    # fontes
    size_chars = Counter()
    for _, ln in all_lines:
        size_chars[ln["size"]] += len(ln["text"])
    body_size = size_chars.most_common(1)[0][0] if size_chars else 10
    res["fonte_corpo_pt"] = body_size
    res["tamanhos_de_fonte"] = sorted(size_chars.items(), key=lambda kv: -kv[1])[:10]

    # colunas (paginas 2..n-1)
    pw = doc[0].rect.width
    col_votes = Counter()
    for pno in range(2, doc.page_count):
        lines = [ln for p, ln in all_lines if p == pno]
        col_votes[detect_columns(lines, pw)] += 1
    res["layout"] = col_votes.most_common(1)[0][0] if col_votes else detect_columns([ln for _, ln in all_lines], pw)

    # cabecalho/rodape repetidos
    line_pages = defaultdict(set)
    for pno, ln in all_lines:
        t = re.sub(r"\d+", "#", ln["text"]).strip()
        if 3 < len(t) < 120:
            line_pages[t].add(pno)
    repeated = [t for t, ps in line_pages.items() if len(ps) >= max(3, doc.page_count // 2)]
    res["cabecalho_rodape_repetidos"] = repeated[:10]

    # front matter (paginas 1-2)
    front = [ln for p, ln in all_lines if p <= 2]
    front_text = "\n".join(ln["text"] for ln in front)
    big = sorted({ln["size"] for ln in front}, reverse=True)
    title_cands = [ln["text"] for ln in front if ln["size"] >= body_size * 1.3][:8]
    res["front_matter"] = {
        "candidatos_titulo": title_cands,
        "dois_maiores_tamanhos": big[:2],
        "dois": None,
        "doi": sorted(set(RE_DOI.findall(front_text)))[:5],
        "issn": sorted(set(RE_ISSN.findall(front_text)) - set(RE_ORCID.findall(front_text)))[:5],
        "orcid": sorted(set(RE_ORCID.findall(front_text)))[:10],
        "emails": sorted(set(RE_EMAIL.findall(front_text)))[:10],
        "linhas_com_datas": [ln["text"] for ln in front if RE_DATE_HINT.search(ln["text"])][:8],
        "marcadores": {k: [ln["text"] for ln in front if rx.search(ln["text"])][:4] for k, rx in MARKERS.items() if k in ("resumo", "palavras")},
        "superscritos_p1": [ln["sup"] for ln in front if ln["sup"]][:10],
    }
    del res["front_matter"]["dois"]

    # marcadores globais (em todas as paginas) + ORCID/DOI/emails no doc inteiro
    full_text = "\n".join(ln["text"] for _, ln in all_lines)
    res["identificadores_documento"] = {
        "doi": sorted(set(RE_DOI.findall(full_text)))[:8],
        "orcid": sorted(set(RE_ORCID.findall(full_text)))[:10],
        "emails": sorted(set(RE_EMAIL.findall(full_text)))[:10],
    }
    res["marcadores"] = {
        k: [{"pagina": p, "texto": ln["text"]} for p, ln in all_lines if rx.search(ln["text"])][:6]
        for k, rx in MARKERS.items()
    }

    # titulos de secao: negrito ou maior que o corpo, curtos, nao no rodape
    headings = []
    for pno, ln in all_lines:
        t = ln["text"]
        if len(t) > 110 or len(t) < 3:
            continue
        is_num = bool(RE_NUMBERED_HEADING.match(t))
        if (ln["bold"] and ln["size"] >= body_size * 0.95) or ln["size"] >= body_size * 1.15 or (is_num and ln["bold"]):
            if RE_FIG.match(t):
                continue
            headings.append({"pagina": pno, "texto": t, "size": ln["size"], "bold": ln["bold"], "numerada": is_num})
    res["titulos_secao"] = headings[:60]

    # notas de rodape: fonte menor no terco inferior da pagina
    ph = doc[0].rect.height
    fn_lines = [(p, ln) for p, ln in all_lines if ln["size"] <= body_size * 0.88 and ln["bbox"][1] > ph * 0.62 and len(ln["text"]) > 15]
    fn_starts = [(p, ln["text"]) for p, ln in fn_lines if re.match(r"^\s*\d{1,3}\s", ln["text"]) or ln["sup"]]
    res["notas_rodape"] = {
        "linhas_em_fonte_pequena_no_pe": len(fn_lines),
        "inicios_de_nota_detectados": len(fn_starts),
        "exemplos": [t for _, t in fn_starts[:5]],
        "paginas_com_notas": sorted({p for p, _ in fn_starts}),
    }

    # referencias
    ref_pages = [m["pagina"] for m in res["marcadores"]["referencias"]]
    ref_entries = []
    if ref_pages:
        start = ref_pages[-1]
        for p, ln in all_lines:
            if p >= start and RE_REF_ENTRY.match(ln["text"]):
                ref_entries.append(ln["text"])
    res["referencias"] = {
        "pagina_inicio": ref_pages[-1] if ref_pages else None,
        "entradas_detectadas": len(ref_entries),
        "exemplos": ref_entries[:5],
        "estilo": "ABNT (SOBRENOME, Nome)" if ref_entries else "nao detectado",
    }

    # citacoes no texto
    cites = RE_CITATION.findall(full_text)
    res["citacoes_no_texto"] = {"total": len(cites), "exemplos": [f"({a}, {y})" for a, y in cites[:6]]}

    # figuras e tabelas por legenda
    figs = [{"pagina": p, "texto": ln["text"][:90]} for p, ln in all_lines if RE_FIG.match(ln["text"])]
    res["figuras_tabelas"] = {"legendas": figs[:20], "total_imagens": sum(images_per_page)}

    # dump texto
    os.makedirs("poc/saida", exist_ok=True)
    with open(f"poc/saida/{name}.txt", "w", encoding="utf-8") as f:
        for pno, page in enumerate(doc, start=1):
            f.write(f"\n===== PAGINA {pno} =====\n")
            for ln in page_lines(page):
                flag = ("B" if ln["bold"] else " ") + ("I" if ln["italic"] else " ")
                sup = f" [sup:{','.join(ln['sup'])}]" if ln["sup"] else ""
                f.write(f"{ln['size']:>5} {flag} x{ln['bbox'][0]:>5.0f} | {ln['text']}{sup}\n")
    with open(f"poc/saida/{name}.json", "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=2)
    return res


def md_summary(r):
    fm = r["front_matter"]
    return "\n".join(
        [
            f"### {r['arquivo']}",
            f"- páginas: {r['paginas']} · layout: {r['layout']} · fonte do corpo: {r['fonte_corpo_pt']} pt · texto extraível: {r['texto_extraivel']} · imagens: {r['figuras_tabelas']['total_imagens']}",
            f"- produtor: {r['metadata'].get('producer','?')} / criador: {r['metadata'].get('creator','?')} · título nos metadados: {r['metadata'].get('title','')[:80]!r}",
            f"- candidatos a título (fonte ≥ 1,3× corpo): {fm['candidatos_titulo'][:4]}",
            f"- DOI: {r['identificadores_documento']['doi'][:3]} · ISSN: {fm['issn']} · ORCID: {len(r['identificadores_documento']['orcid'])} · e-mails: {len(r['identificadores_documento']['emails'])}",
            f"- datas: {fm['linhas_com_datas'][:3]}",
            f"- resumo/palavras-chave: {fm['marcadores']}",
            f"- cabeçalho/rodapé repetidos: {r['cabecalho_rodape_repetidos'][:4]}",
            f"- títulos de seção detectados: {len(r['titulos_secao'])} · numerados: {sum(1 for h in r['titulos_secao'] if h['numerada'])}",
            f"- notas de rodapé: {r['notas_rodape']['inicios_de_nota_detectados']} inícios em {len(r['notas_rodape']['paginas_com_notas'])} páginas",
            f"- referências: início p.{r['referencias']['pagina_inicio']} · {r['referencias']['entradas_detectadas']} entradas · {r['referencias']['estilo']}",
            f"- citações (AUTOR, ano) no texto: {r['citacoes_no_texto']['total']}",
            f"- legendas de figura/tabela: {len(r['figuras_tabelas']['legendas'])}",
            f"- anotações PDF: {r['total_anotacoes']} · retângulos desenhados: {r['retangulos_desenhados']} · anexos: {r['anexos_embutidos']}",
            "",
        ]
    )


if __name__ == "__main__":
    paths = []
    for arg in sys.argv[1:]:
        paths.extend(glob.glob(arg))
    if not paths:
        print("Nenhum PDF encontrado.")
        sys.exit(1)
    for p in paths:
        try:
            r = analyse(p)
            print(md_summary(r))
        except Exception as e:  # noqa: BLE001
            print(f"### {p}\n- ERRO: {e}\n")
