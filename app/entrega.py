"""
Entrega do pacote à SciELO: conferência do .zip, relatório de validação e depósito no FTP da coleção.

Base documental (os dois PDF que o Murillo indicou, lidos em 05/09/2026):

1. "Guia de Entrega de Pacote XML para Publicação em SciELO" (versão dez/2024)
   - O pacote é um .zip. .rar não é aceito.
   - Formatos: imagens .tiff, .jpg ou .png; XML .xml; relatório do validador .html;
     material suplementar de preferência .pdf; vídeos .mp4.
   - Tabelas, fórmulas e equações têm de estar codificadas em MathML ou LaTeX, podendo ter
     equivalente em .svg. (É por isso que o gerador exige o LaTeX das equações.)
   - Nome de arquivo não pode ter ponto final, underline nem acentos.
   - O pacote leva o XML do artigo, o PDF por idioma, as imagens, o relatório do validador e os
     demais materiais. Em publicação contínua não vai sumário em PDF.
   - Publicação contínua exige <article-id pub-id-type="other"> com exatamente 5 dígitos, criado
     pelo provedor do XML junto com a planilha de "Other" da SciELO. O título da seção tem de ser
     idêntico no PDF, na planilha e no XML, senão o pacote é devolvido.
   - Depósito: o .zip vai para o FTP da SciELO, na pasta "Entrega" (correções vão em "Correcao").
     As credenciais do FTP são pedidas a publicacao@scielo.org.
   - Depositar não basta: é obrigatório avisar publicacao@scielo.org por e-mail a cada depósito.

2. "Atestado de capacidade técnica" (versão out/2025) — o "selo" a que o Murillo se referia
   - Só pessoa jurídica (CNPJ, ou documento formal equivalente para empresa estrangeira).
   - Vale para quem atende as coleções SciELO Brasil, SciELO Saúde Pública, RevEnf e Pepsic.
   - O pedido é por e-mail a publicacao@scielo.org, com nome da empresa e CNPJ, solicitando a
     amostra de avaliação.
   - Prazo total de 30 a 60 dias corridos: a empresa tem 15 dias para devolver a amostra marcada,
     a SciELO tem 15 dias para avaliar, e pode haver uma segunda rodada de 15 + 15.
   - Qualquer programa de marcação serve, desde que a saída seja compatível com a SPS/JATS e venha
     acompanhada do relatório do validador.
   - Aprovada, a empresa entra na lista de parceiras e segue sendo avaliada a cada entrega.
     Reprovada, só pode enviar nova amostra depois de 6 meses.

O que dá e o que não dá para fazer daqui: a SciELO não publica API de depósito. O que existe é o
FTP e o e-mail — e os dois o sistema faz. O pedido do atestado é um e-mail, que o correio do
sistema monta e envia. O que não dá é "clicar e publicar": a avaliação é humana, na SciELO.
"""
import ftplib
import io
import os
import re
import ssl
import unicodedata
from pathlib import Path
from typing import Optional

EMAIL_SCIELO = "publicacao@scielo.org"
PASTA_ENTREGA = "Entrega"
PASTA_CORRECAO = "Correcao"
COLECOES_ATESTADO = ["SciELO Brasil", "SciELO Saúde Pública", "RevEnf", "Pepsic"]
EXT_IMAGEM = {".tif", ".tiff", ".jpg", ".jpeg", ".png"}
EXT_ACEITAS = EXT_IMAGEM | {".xml", ".pdf", ".html", ".mp4", ".svg"}
RE_NOME_OK = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]*\.[A-Za-z0-9]+$")


# ---------------------------------------------------------------- conferência do pacote

def _sem_acento(s: str) -> bool:
    return all(unicodedata.category(c) != "Mn" for c in unicodedata.normalize("NFD", s))


def confere_nome(nome: str) -> Optional[str]:
    """Regras de nome do guia: sem ponto (fora o da extensão), sem underline, sem acento."""
    base, ext = os.path.splitext(nome)
    if not _sem_acento(nome):
        return "tem acento"
    if "_" in nome:
        return "tem underline"
    if "." in base:
        return "tem ponto além do da extensão"
    if " " in nome:
        return "tem espaço"
    if ext.lower() not in EXT_ACEITAS:
        return f"extensão {ext or '(nenhuma)'} não está na lista do guia ({', '.join(sorted(EXT_ACEITAS))})"
    if not RE_NOME_OK.match(nome):
        return "usa caractere fora de letras, números e hífen"
    return None


def confere_pacote(caminho_zip: str) -> dict:
    """Confere o .zip contra o guia de entrega e contra o validador do packtools.

    Devolve {'ok', 'itens': [{'que','ok','detalhe'}], 'arquivos': [...], 'erros_xml': [...]}.
    """
    import zipfile

    itens = []
    erros_xml = []

    def item(que, ok, detalhe=""):
        itens.append({"que": que, "ok": bool(ok), "detalhe": detalhe})

    if not os.path.exists(caminho_zip):
        return {"ok": False, "itens": [{"que": "Pacote existe", "ok": False, "detalhe": "o .zip ainda não foi gerado"}],
                "arquivos": [], "erros_xml": []}
    item("Formato do pacote", caminho_zip.lower().endswith(".zip"),
         "o guia aceita .zip; .rar não é aceito")
    with zipfile.ZipFile(caminho_zip) as z:
        nomes = [n for n in z.namelist() if not n.endswith("/")]
    curtos = [os.path.basename(n) for n in nomes]
    problemas = [(n, m) for n in curtos if (m := confere_nome(n))]
    item("Nome dos arquivos", not problemas,
         "; ".join(f"{n}: {m}" for n, m in problemas) if problemas else
         "sem ponto extra, underline, acento ou espaço, como o guia exige")
    item("Arquivos na raiz do pacote", all("/" not in n for n in nomes),
         "a SciELO espera os arquivos direto na raiz do .zip" if any("/" in n for n in nomes) else "")
    xmls = [n for n in curtos if n.lower().endswith(".xml")]
    item("XML do artigo", len(xmls) == 1, f"{len(xmls)} arquivo(s) .xml no pacote")
    pdfs = [n for n in curtos if n.lower().endswith(".pdf")]
    item("PDF do artigo", bool(pdfs), "o pacote leva o PDF de cada idioma" if not pdfs else ", ".join(pdfs))
    relat = [n for n in curtos if n.lower().endswith(".html")]
    item("Relatório do validador", bool(relat),
         "o guia pede o relatório de validação em .html junto do pacote" if not relat else relat[0])
    imagens = [n for n in curtos if os.path.splitext(n)[1].lower() in EXT_IMAGEM]
    item("Formato das imagens", True, f"{len(imagens)} imagem(ns): {', '.join(sorted(imagens)[:6]) or 'nenhuma'}")

    # Validação do XML e dos arquivos que ele cita. O validate_zip_package do packtools resolve o DTD pela
    # URL do DOCTYPE, o que não funciona sem rede; o projeto já valida pelo DTD empacotado, e é esse caminho
    # que usamos aqui — o mesmo que gera o resultado mostrado na tela do documento.
    import tempfile

    if xmls:
        temp = tempfile.mkdtemp(prefix="xmljats-conf-")
        try:
            with zipfile.ZipFile(caminho_zip) as z:
                interno = next(n for n in z.namelist() if os.path.basename(n) == xmls[0])
                destino = os.path.join(temp, xmls[0])
                with open(destino, "wb") as saida:
                    saida.write(z.read(interno))
            from gerar_xml import valida_packtools
            dtd_ok, sps_ok, erros, _ = valida_packtools(destino)
            erros_xml.extend(erros[:40])
            item("XML válido no DTD JATS", dtd_ok is True,
                 "; ".join(e for e in erros if "DTD" in e)[:200] if dtd_ok is not True else "")
            item("XML válido no Schematron SciELO PS", sps_ok is True,
                 "; ".join(e for e in erros if "DTD" not in e)[:200] if sps_ok is not True else "")
            faltando = _arquivos_citados(destino) - set(curtos)
            item("Arquivos citados pelo XML estão no pacote", not faltando,
                 ("faltam: " + ", ".join(sorted(faltando))) if faltando else "nenhuma referência solta")
        except Exception as e:  # noqa: BLE001
            item("Validação do XML", False, f"não consegui validar: {str(e)[:150]}")
        finally:
            import shutil
            shutil.rmtree(temp, ignore_errors=True)

    return {"ok": all(i["ok"] for i in itens), "itens": itens, "arquivos": sorted(curtos), "erros_xml": erros_xml}


def _arquivos_citados(caminho_xml: str) -> set:
    """Nomes de arquivo que o XML referencia (graphic, media, material suplementar)."""
    from lxml import etree

    XLINK = "{http://www.w3.org/1999/xlink}href"
    parser = etree.XMLParser(load_dtd=False, resolve_entities=False, no_network=True, recover=True)
    arvore = etree.parse(caminho_xml, parser)
    citados = set()
    for el in arvore.iter():
        href = el.get(XLINK)
        if not href or href.startswith(("http://", "https://", "mailto:", "ftp://")):
            continue
        citados.add(os.path.basename(href))
    return citados


def relatorio_html(nome_base: str, validacao: dict, conferencia: dict) -> bytes:
    """Relatório de validação para ir dentro do pacote, como o guia pede."""
    def linhas(titulo, lista):
        if not lista:
            return f"<h2>{titulo}</h2><p class='ok'>nenhum</p>"
        itens = "".join(f"<li>{_escapa(str(x))}</li>" for x in lista)
        return f"<h2>{titulo} ({len(lista)})</h2><ul>{itens}</ul>"

    checks = "".join(
        f"<tr><td>{_escapa(i['que'])}</td><td class='{'ok' if i['ok'] else 'erro'}'>{'ok' if i['ok'] else 'falta'}</td>"
        f"<td>{_escapa(i['detalhe'])}</td></tr>" for i in conferencia.get("itens", []))
    corpo = f"""<!doctype html><html lang="pt-BR"><meta charset="utf-8">
<title>Relatório de validação — {_escapa(nome_base)}</title>
<style>body{{font:14px/1.6 system-ui,sans-serif;max-width:60em;margin:2em auto;padding:0 1em;color:#131a24}}
h1{{font-size:20px}} h2{{font-size:15px;margin-top:1.6em}} table{{border-collapse:collapse;width:100%}}
td,th{{border:1px solid #d5dce6;padding:6px 10px;text-align:left;vertical-align:top}}
.ok{{color:#12603f}} .erro{{color:#b3261e}} li{{margin:.2em 0}} code{{font-family:ui-monospace,monospace}}</style>
<h1>Relatório de validação — {_escapa(nome_base)}</h1>
<p>Gerado pelo xmljats com o packtools, o validador oficial da SciELO. Acompanha o pacote, como pede o
Guia de Entrega de Pacote XML para Publicação em SciELO.</p>
<h2>Validação do XML</h2>
<table><tr><th>Verificação</th><th>Resultado</th></tr>
<tr><td>DTD JATS</td><td class="{'ok' if validacao.get('dtd_ok') else 'erro'}">{'válido' if validacao.get('dtd_ok') else 'inválido'}</td></tr>
<tr><td>Schematron SciELO PS</td><td class="{'ok' if validacao.get('sps_ok') else 'erro'}">{'válido' if validacao.get('sps_ok') else 'com apontamentos'}</td></tr>
</table>
<h2>Conferência do pacote</h2>
<table><tr><th>Item</th><th>Resultado</th><th>Detalhe</th></tr>{checks}</table>
{linhas("Apontamentos do packtools", validacao.get("erros") or [])}
{linhas("Bloqueantes das nossas regras", validacao.get("bloqueantes") or [])}
{linhas("Avisos", validacao.get("avisos") or [])}
</html>"""
    return corpo.encode("utf-8")


def _escapa(t: str) -> str:
    return (t or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# ---------------------------------------------------------------- depósito no FTP

def config_ftp(cfg: dict) -> dict:
    """Configuração do FTP da SciELO guardada em config.json, com a senha nunca exposta inteira."""
    f = (cfg or {}).get("scielo_ftp") or {}
    senha = f.get("senha") or ""
    return {
        "servidor": f.get("servidor") or "", "porta": int(f.get("porta") or 21),
        "usuario": f.get("usuario") or "", "tem_senha": bool(senha),
        "senha_mascarada": (senha[:2] + "…" + senha[-2:]) if len(senha) > 6 else ("…" if senha else ""),
        "tls": bool(f.get("tls", True)), "pasta_entrega": f.get("pasta_entrega") or PASTA_ENTREGA,
        "pasta_correcao": f.get("pasta_correcao") or PASTA_CORRECAO,
        "pronto": bool(f.get("servidor") and f.get("usuario") and senha),
    }


def _conecta(f: dict, timeout: int = 30):
    """Conexão FTP, com TLS quando o servidor aceitar. Devolve (conexao, como)."""
    servidor, porta, usuario, senha = f["servidor"], int(f.get("porta") or 21), f["usuario"], f["senha"]
    if f.get("tls", True):
        # com TLS pedido, não caímos para texto claro por conta própria: seria mandar a senha do FTP da
        # SciELO em claro sem ninguém autorizar. Quem quiser FTP simples desmarca a opção em Configurações.
        ctx = ssl.create_default_context()
        con = ftplib.FTP_TLS(context=ctx, timeout=timeout)
        con.connect(servidor, porta)
        con.login(usuario, senha)
        con.prot_p()
        return con, "FTPS (canal de dados cifrado)"
    con = ftplib.FTP(timeout=timeout)
    con.connect(servidor, porta)
    con.login(usuario, senha)
    return con, "FTP simples, sem TLS: a senha trafega em texto claro"


def deposita(cfg: dict, caminho_zip: str, correcao: bool = False, timeout: int = 60) -> dict:
    """Envia o .zip para o FTP da SciELO. Devolve {'ok','mensagem','passos':[...]}.
    Nunca levanta exceção de rede: o que der errado volta na mensagem."""
    f = (cfg or {}).get("scielo_ftp") or {}
    if not (f.get("servidor") and f.get("usuario") and f.get("senha")):
        return {"ok": False, "mensagem": "O FTP da SciELO ainda não está configurado. As credenciais são pedidas a "
                                         f"{EMAIL_SCIELO}, e depois vão em Configurações.", "passos": []}
    if not os.path.exists(caminho_zip):
        return {"ok": False, "mensagem": "O pacote .zip ainda não foi gerado.", "passos": []}
    pasta = (f.get("pasta_correcao") or PASTA_CORRECAO) if correcao else (f.get("pasta_entrega") or PASTA_ENTREGA)
    nome = os.path.basename(caminho_zip)
    passos = []
    con = None
    try:
        con, como = _conecta(f, timeout=timeout)
        passos.append(f"Conectado em {f['servidor']}:{f.get('porta') or 21} como {f['usuario']} — {como}.")
        try:
            con.cwd(pasta)
            passos.append(f"Entrei na pasta {pasta}.")
        except ftplib.error_perm as e:
            return {"ok": False, "passos": passos,
                    "mensagem": f"A pasta '{pasta}' não existe ou a conta não tem acesso a ela ({e}). "
                                f"Confirme o nome da pasta com {EMAIL_SCIELO}."}
        # sobe com outro nome e só depois renomeia: uma queda no meio do envio deixaria um .zip truncado
        # na pasta Entrega da SciELO, que é pior do que não ter enviado nada
        parcial = nome + ".parcial"
        with open(caminho_zip, "rb") as arq:
            con.storbinary(f"STOR {parcial}", arq)
        try:
            con.delete(nome)  # reenvio do mesmo pacote: o rename não sobrescreve em todo servidor
        except ftplib.all_errors:
            pass
        con.rename(parcial, nome)
        passos.append(f"Enviei {nome} ({os.path.getsize(caminho_zip)} bytes), com nome provisório até terminar.")
        try:
            tamanho = con.size(nome)
            confere = tamanho == os.path.getsize(caminho_zip)
            passos.append(f"O servidor confirma {tamanho} bytes." if confere else
                          f"Atenção: o servidor informa {tamanho} bytes, e o arquivo tem {os.path.getsize(caminho_zip)}.")
        except Exception:  # noqa: BLE001
            passos.append("O servidor não informou o tamanho do arquivo depositado.")
        return {"ok": True, "passos": passos,
                "mensagem": f"{nome} depositado em {pasta}. Falta o aviso por e-mail: depositar sozinho não garante "
                            f"publicação, o guia exige avisar {EMAIL_SCIELO} a cada depósito."}
    except ssl.SSLError as e:
        return {"ok": False, "passos": passos,
                "mensagem": f"O servidor não aceitou TLS ({str(e)[:120]}). Se a SciELO usar FTP simples, desmarque "
                            f"\"Usar TLS\" em Configurações — ciente de que a senha passa a trafegar em texto claro."}
    except ftplib.all_errors as e:
        return {"ok": False, "passos": passos, "mensagem": f"O FTP recusou: {str(e)[:200]}"}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "passos": passos, "mensagem": f"Não consegui depositar: {str(e)[:200]}"}
    finally:
        if con is not None:
            try:
                con.quit()
            except Exception:  # noqa: BLE001
                try:
                    con.close()
                except Exception:  # noqa: BLE001
                    pass


def testa_conexao(cfg: dict, timeout: int = 25) -> dict:
    """Só conecta e lista as pastas, para conferir credenciais sem depositar nada."""
    f = (cfg or {}).get("scielo_ftp") or {}
    if not (f.get("servidor") and f.get("usuario") and f.get("senha")):
        return {"ok": False, "mensagem": "Preencha servidor, usuário e senha do FTP primeiro.", "pastas": []}
    con = None
    try:
        con, como = _conecta(f, timeout=timeout)
        pastas = con.nlst()
        return {"ok": True, "mensagem": f"Conectado — {como}.", "pastas": sorted(pastas)[:40]}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "mensagem": f"Não consegui conectar: {str(e)[:200]}", "pastas": []}
    finally:
        if con is not None:
            try:
                con.quit()
            except Exception:  # noqa: BLE001
                pass


# ---------------------------------------------------------------- e-mails obrigatórios

def email_deposito(nome_base: str, revista: dict, doc: dict, correcao: bool = False) -> tuple:
    """Texto do aviso de depósito, que o guia torna obrigatório a cada envio."""
    titulo = doc.get("titulo") or nome_base
    assunto = (f"{'Correção' if correcao else 'Depósito'} de pacote XML — {revista.get('titulo') or ''} "
               f"({revista.get('issn_epub') or ''}) — {nome_base}")
    corpo = f"""Prezados,

{'Depositamos uma correção' if correcao else 'Depositamos um pacote'} no FTP da SciELO, na pasta {PASTA_CORRECAO if correcao else PASTA_ENTREGA}.

Periódico: {revista.get('titulo') or '—'}
ISSN: {revista.get('issn_epub') or '—'}
Acrônimo: {revista.get('acronimo') or '—'}
Pacote: {nome_base}.zip
Artigo: {titulo}
DOI: {doc.get('doi') or '—'}
Volume/número: {doc.get('volume') or '—'} / {doc.get('numero') or '—'}
Seção: {doc.get('heading') or '—'}

O pacote leva o XML em SciELO PS, o PDF, as imagens e o relatório de validação em HTML.

Atenciosamente,
"""
    return assunto, corpo


def email_atestado(empresa: str, cnpj: str, contato: str) -> tuple:
    """Pedido do atestado de capacidade técnica (o 'selo'), no formato que o documento da SciELO descreve."""
    assunto = f"Solicitação de atestado de capacidade técnica — {empresa}"
    corpo = f"""Prezados,

Solicitamos a amostra para avaliação do atestado de capacidade técnica para marcação de XML em
SciELO PS, conforme o documento "Atestado de capacidade técnica".

Empresa: {empresa}
CNPJ: {cnpj}
Contato: {contato}
Coleções de interesse: {', '.join(COLECOES_ATESTADO)}

Ficamos no aguardo do arquivo de amostra e das orientações. Estamos cientes do prazo de 15 dias
corridos para devolver a amostra marcada, acompanhada do relatório do validador.

Atenciosamente,
{empresa}
"""
    return assunto, corpo
