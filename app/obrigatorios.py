"""
Campos que a SciELO exige e que o PDF muitas vezes não tem: a lista, a fonte de cada regra e o que
falta preencher em cada documento.

De onde saiu a lista (não é opinião nossa):

1. Schematron oficial da SPS, que é o que o packtools roda para aprovar o pacote. Arquivos
   `scielo-style-1.9.sch` e `scielo-style-1.10.sch` dentro do packtools. Cada regra abaixo cita o
   `id` do pattern correspondente, então dá para conferir uma por uma.
2. "Guia de Entrega de Pacote XML para Publicação em SciELO" (versão dez/2024), de onde vem a
   exigência de fórmulas e tabelas codificadas em MathML ou LaTeX e o article-id "other" de 5 dígitos
   na publicação contínua.

O que a SciELO exige e o PDF quase nunca traz — que é o que o Murillo lembrava em parte:

  Licença Creative Commons      pattern `license` / `license_attributes`
  Seção da revista (heading)    pattern `article_categories` / `subj_group`
  Data de publicação completa   pattern `pub-date_type_pub` (dia, mês e ano)
  Datas de recebido e aceito    `history` (a SciELO cobra em artigo original)
  Order de 5 dígitos            guia de entrega, publicação contínua
  DOI                           `article-id_values`
  Volume e elocation/páginas    `volume_notempty`, `fpage_or_elocation-id`
  ORCID de cada autor           `contrib-id-type-values` + exigência da coleção
  Instituição e país de cada afiliação   `aff_contenttypes`, `aff_country`, `aff_country-attrs`
  E-mail do autor correspondente         `author-notes/corresp`
  Resumo e palavras-chave       `abstract`, `kwdgroup_lang`
  Legenda de figura e tabela    `caption_title` (caption sem title é erro)
  Título de cada seção          `sectitle`
  Fórmula em MathML/LaTeX       guia de entrega

Cada item vira um campo do formulário de revisar e editar. Enquanto faltar, o documento não salva
nem valida: é o que foi pedido, e é também o que a SciELO faria devolvendo o pacote.
"""
import re
from typing import Optional

RE_ISO = re.compile(r"^\d{4}-\d{2}-\d{2}$")
RE_ORDER = re.compile(r"^\d{5}$")
RE_DOI = re.compile(r"^10\.\d{4,9}/\S+$")
RE_CC = re.compile(r"^https?://creativecommons\.org/licenses/")
# tipos em que a SPS cobra resumo e histórico de datas (pattern `abstract`, contexto research/review)
TIPOS_COM_RESUMO = {"research-article", "review-article"}

# rótulo curto de cada campo, para a mensagem de pendência ficar legível
ROTULOS = {
    "heading": "Seção da revista", "licenca": "Licença", "doi": "DOI", "order": "Order (5 dígitos)",
    "volume": "Volume", "elocation": "elocation-id", "tipo_artigo": "Tipo de artigo", "idioma": "Idioma",
    "data_publicado": "Data de publicação", "data_recebido": "Data de recebimento", "data_aceito": "Data de aceite",
    "revista": "Revista",
}


def _vivos(lista) -> list:
    """Itens que ainda contam: os marcados para remover na tela não são cobrados nem vão para o XML."""
    return [(i, x) for i, x in enumerate(lista or []) if not (isinstance(x, dict) and x.get("_removido"))]


def _vazio(v) -> bool:
    return v is None or (isinstance(v, str) and not v.strip()) or (isinstance(v, (list, dict)) and not v)


def _reg(saida, campo, motivo, fonte):
    saida[campo] = {"motivo": motivo, "fonte": fonte}


def pendencias(modelo: dict, revista: Optional[dict], versao_sps: str = "1.9") -> dict:
    """Campos obrigatórios que ainda estão vazios: {campo_do_formulario: {'motivo','fonte'}}.

    Recebe o modelo já com as edições aplicadas, então o que aparece aqui é o que de fato falta.
    """
    p: dict = {}
    m = modelo or {}
    tipo = (m.get("tipo_artigo") or "research-article").strip()
    d = m.get("datas") or {}

    # ---- revista (journal-meta): sem cadastro não há acrônimo, título abreviado nem editora
    if not revista:
        _reg(p, "revista", "Escolha a revista (ou informe o ISSN): o acrônimo, o título abreviado e a editora "
                           "não estão no PDF e entram no journal-meta e no nome dos arquivos.",
             "SPS: journal-id_has_publisher-id, has_journal-title_and_abbrev-journal-title, publisher")

    # ---- identificação do artigo
    if _vazio(m.get("heading")):
        _reg(p, "heading", "A SciELO exige a seção da revista (Artigos, Dossiê, Resenhas…). Ela precisa ser idêntica "
                           "no PDF, na planilha do lote e no XML, senão o pacote é devolvido.",
             "SPS: article_categories, subj_group · Guia de entrega, item Sumário")
    if _vazio(m.get("doi")) or not RE_DOI.match((m.get("doi") or "").strip()):
        _reg(p, "doi", "DOI do artigo, no formato 10.xxxx/sufixo. Pegue no OJS ou no registro do Crossref.",
             "SPS: article-id_values")
    if not RE_ORDER.match((m.get("order") or "").strip()):
        _reg(p, "order", "Order com exatamente 5 dígitos. É criado pelo provedor do XML junto com a planilha de Other "
                         "da SciELO e identifica o artigo no lote.",
             "Guia de entrega, item Publicação contínua · SPS: article-id_values")
    if _vazio(m.get("volume")):
        _reg(p, "volume", "Volume do fascículo.", "SPS: volume_notempty")
    if _vazio(m.get("elocation")) and _vazio(m.get("fpage")):
        _reg(p, "elocation", "elocation-id (publicação contínua) ou primeira página (fascículo regular).",
             "SPS: fpage_or_elocation-id, elocation-id")
    if _vazio(m.get("idioma")):
        _reg(p, "idioma", "Idioma do artigo, que vai no xml:lang do <article>.", "SPS: article_attributes")

    # ---- licença
    url = (m.get("licenca_url") or "").strip()
    if not RE_CC.match(url):
        _reg(p, "licenca", "Licença Creative Commons do artigo. A SPS só aceita permissions/license com "
                           "license-type='open-access' e link para creativecommons.org/licenses/.",
             "SPS: license, license_attributes")

    # ---- datas
    if not RE_ISO.match((d.get("publicado") or "").strip()):
        _reg(p, "data_publicado", "Data de publicação com dia, mês e ano. O PDF costuma trazer só o ano; o dia e o mês "
                                  "estão no OJS, na página do artigo.",
             "SPS: pub-date_type_pub, pub-date_date_type")
    if tipo in TIPOS_COM_RESUMO:
        for campo, rot in (("recebido", "recebimento"), ("aceito", "aceite")):
            if not RE_ISO.match((d.get(campo) or "").strip()):
                _reg(p, f"data_{campo}", f"Data de {rot}. Está no OJS, no histórico da submissão.", "SPS: history")

    # ---- título
    titulos = m.get("titulos") or []
    if not titulos or _vazio(titulos[0].get("texto")):
        _reg(p, "titulo_0_texto", "Título do artigo.", "SPS: article-title")

    # ---- autoria
    autores = [x for _, x in _vivos(m.get("autores"))]
    if not autores:
        _reg(p, "autor_0_sobrenome", "Pelo menos um autor. Se o motor não leu a autoria do PDF, digite aqui.",
             "SPS: contrib-group / aff_contenttypes_contribgroup")
    for i, a in _vivos(m.get("autores")):
        if _vazio(a.get("sobrenome")):
            _reg(p, f"autor_{i}_sobrenome", f"Sobrenome do autor {i + 1}.", "SPS: contrib-group")
        if _vazio(a.get("orcid")) or a.get("orcid_valido") is False:
            _reg(p, f"autor_{i}_orcid", f"ORCID de {a.get('nome_completo') or f'autor {i + 1}'}. A SciELO exige ORCID "
                                        f"de todos os autores; peça ao autor ou busque em orcid.org.",
                 "SPS: contrib-id_attributes, contrib-id-type-values")
        if not a.get("aff_ids"):
            _reg(p, f"autor_{i}_affs", f"Afiliação de {a.get('nome_completo') or f'autor {i + 1}'} (id da lista abaixo).",
                 "SPS: xref-reftype-integrity-aff")
    if autores and not any(a.get("email") for a in autores):
        _reg(p, "corresp", "E-mail do autor correspondente: marque quem é e preencha o e-mail dele.",
             "SPS: author-notes/corresp · fn_attributes")

    # ---- afiliações
    for j, af in _vivos(m.get("afiliacoes")):
        if _vazio(af.get("instituicao")):
            _reg(p, f"aff_{j}_instituicao", f"Instituição da afiliação {af.get('id') or j + 1}.",
                 "SPS: aff_contenttypes (institution content-type='original' e 'orgname')")
        if _vazio(af.get("pais_iso")):
            _reg(p, f"aff_{j}_pais_iso", f"País da afiliação {af.get('id') or j + 1}, em sigla ISO (BR, AR, PT…).",
                 "SPS: aff_country, aff_country-attrs")

    # ---- resumo e palavras-chave
    resumos = [x for _, x in _vivos(m.get("resumos"))]
    if tipo in TIPOS_COM_RESUMO:
        if not resumos:
            _reg(p, "resumo_0_texto", "Resumo no idioma do artigo. Artigo original e de revisão não passam sem resumo.",
                 "SPS: abstract")
        for k, r in _vivos(m.get("resumos")):
            if _vazio(r.get("texto")):
                _reg(p, f"resumo_{k}_texto", f"Texto do resumo em {r.get('idioma') or 'idioma não definido'}.", "SPS: abstract")
            if _vazio(r.get("idioma")):
                _reg(p, f"resumo_{k}_idioma", "Idioma do resumo (vai no xml:lang).", "SPS: kwdgroup_lang, abstract")
            if not r.get("palavras_chave"):
                _reg(p, f"resumo_{k}_kw", f"Palavras-chave em {r.get('idioma') or 'cada idioma'}: a SPS pede um "
                                          f"kwd-group por idioma de resumo.", "SPS: kwdgroup_lang")

    # ---- corpo
    secoes = [x for _, x in _vivos(m.get("secoes"))]
    if not secoes:
        _reg(p, "secao_0_titulo", "O corpo do texto precisa de pelo menos uma seção com título.", "SPS: sectitle")
    for k, sec in _vivos(m.get("secoes")):
        if _vazio(sec.get("titulo_completo") or sec.get("titulo")):
            _reg(p, f"secao_{k}_titulo", f"Título da seção {k + 1}.", "SPS: sectitle")

    # ---- tabelas, figuras, quadros e diálogos
    for k, t in _vivos(m.get("tabelas")):
        if _vazio(t.get("legenda")):
            _reg(p, f"tabela_{k}_legenda", f"Legenda de {t.get('rotulo') or f'tabela {k + 1}'}.", "SPS: caption_title")
        if not t.get("celulas") and not t.get("arquivo"):
            _reg(p, f"tabela_{k}_celulas", f"Conteúdo de {t.get('rotulo') or f'tabela {k + 1}'}: uma linha por linha, "
                                           f"colunas separadas por | (colar do Word ou do Excel também funciona).",
                 "Guia de entrega: tabelas codificadas, não como imagem")
    for k, f in _vivos(m.get("figuras")):
        if (f.get("tipo") or "fig") != "fig":
            continue
        if _vazio(f.get("legenda")):
            _reg(p, f"figura_{k}_legenda", f"Legenda de {f.get('rotulo') or f'figura {k + 1}'}.", "SPS: caption_title")
        if _vazio(f.get("arquivo")):
            _reg(p, f"figura_{k}_arquivo", f"Imagem de {f.get('rotulo') or f'figura {k + 1}'}: envie o arquivo, "
                                           f"senão a figura fica de fora do pacote.", "SPS: fig/graphic")
    for k, e in _vivos(m.get("equacoes")):
        if _vazio(e.get("mathml")):
            _reg(p, f"equacao_{k}_latex", f"LaTeX de {e.get('rotulo') or f'equação {k + 1}'}. O guia de entrega exige "
                                          f"fórmula codificada em MathML ou LaTeX; imagem não é aceita.",
                 "Guia de entrega, item Formato dos arquivos")
    for k, q in _vivos(m.get("quadros")):
        if _vazio(q.get("texto")):
            _reg(p, f"quadro_{k}_texto", f"Conteúdo de {q.get('rotulo') or f'quadro {k + 1}'}.", "JATS: boxed-text")
    for k, dl in _vivos(m.get("dialogos")):
        if not dl.get("turnos"):
            _reg(p, f"dialogo_{k}_turnos", f"Falas de {dl.get('rotulo') or f'diálogo {k + 1}'}, uma por linha, "
                                           f"no formato 'Falante: fala'.", "JATS: speech/speaker")

    # ---- referências
    if not (m.get("referencias") or []):
        _reg(p, "_referencias", "Lista de referências vazia. Reprocesse o PDF; se ele realmente não tem referências, "
                                "o artigo não é do tipo que a SciELO trata como original.", "SPS: ref, ref_notempty")
    return p


def grupo_de(campo: str) -> str:
    """Bloco da tela a que o campo pertence."""
    if campo.startswith(("autor_", "corresp")):
        return "Autores"
    if campo.startswith("aff_"):
        return "Afiliações"
    if campo.startswith("resumo_"):
        return "Resumos e palavras-chave"
    if campo.startswith("secao_"):
        return "Seções do corpo"
    if campo.startswith("tabela_"):
        return "Tabelas"
    if campo.startswith("figura_"):
        return "Figuras"
    if campo.startswith("equacao_"):
        return "Equações"
    if campo.startswith(("quadro_", "dialogo_")):
        return "Quadros e diálogos"
    if campo.startswith("data_"):
        return "Datas"
    if campo.startswith("titulo_"):
        return "Títulos"
    return "Revista e identificação"


def por_grupo(pend: dict) -> list:
    """[(grupo, [(campo, motivo, fonte), ...])], na ordem em que aparecem na tela."""
    out = {}
    for campo, info in pend.items():
        out.setdefault(grupo_de(campo), []).append((campo, info["motivo"], info["fonte"]))
    return [(g, itens) for g, itens in out.items()]


def resumo_por_grupo(pend: dict) -> list:
    """Agrupa as pendências pelo bloco da tela, para o aviso do topo do formulário."""
    grupos = {}
    for campo in pend:
        grupos.setdefault(grupo_de(campo), []).append(ROTULOS.get(campo, campo))
    return [{"grupo": g, "campos": v, "quantos": len(v)} for g, v in grupos.items()]
