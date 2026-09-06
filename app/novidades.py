"""Novidades por versão e o que cada pessoa ainda não viu.

As notas de cada versão ficam aqui, no código, porque saem junto com a versão. Cada item diz para quem é:
"todos" (cliente, operador e administrador), "operador" (operador e administrador) ou "admin" (só o painel
administrativo). A filtragem é feita no servidor, antes de montar a janela ou a página: o que é do painel
administrativo nunca chega ao HTML do cliente.

Quem viu o quê: usuarios.json guarda `novidades_vistas`, a última versão que a pessoa dispensou (na janela ou
abrindo a página). Conta nova nasce com a versão atual, porque nada é novidade para quem chegou agora. Conta
antiga sem o campo usa a data do último acesso: o que saiu antes dela não é novidade.
"""
from typing import List, Optional

VERSOES = [
    {"versao": "0.27.0", "data": "2026-09-06", "itens": [
        {"para": "todos", "titulo": "Papéis por revista",
         "texto": "O que você pode fazer numa revista passa a ser um papel nela: secretaria editorial (envia e corrige), corpo editorial "
                  "(acompanha) ou editor-chefe (aprova o XML para a entrega). Quem entra numa organização pelo convite vira secretaria "
                  "editorial nas revistas dela; uma mesma pessoa pode ter papéis diferentes em revistas de organizações diferentes."},
        {"para": "todos", "titulo": "Toda revista de trabalho pertence a uma organização",
         "texto": "Quem tinha uma revista só sua ganhou uma organização com o próprio nome, que aparece em Minha conta. As revistas do "
                  "catálogo (sem organização) continuam abertas a todos. A etapa \"Aprovado pelo editor-chefe\" entra entre "
                  "\"Pronto para entrega\" e \"Entregue à SciELO\"."},
        {"para": "admin", "titulo": "Regras de acesso num lugar só e aprovação do editor-chefe",
         "texto": "app/acesso.py decide quem pode o quê: papéis por revista em papeis.json, administradores e membros na organização, "
                  "migração automática dos dados antigos (membros viram secretaria, quem criou a organização vira admin dela, revista "
                  "particular vira de uma organização pessoal). Revista com editor-chefe: o depósito, por artigo ou por lote, exige a "
                  "aprovação dele. As telas (página da organização, convite com papel, botão de aprovar) vêm na próxima etapa."},
    ]},
    {"versao": "0.26.1", "data": "2026-09-06", "itens": [
        {"para": "admin", "titulo": "Novidade de cliente sem texto de administração",
         "texto": "O item do menu do topo citava Correio e Configurações para o cliente; o texto foi limpo, e o teste passa a impedir "
                  "que item marcado como \"todos\" mencione qualquer coisa do painel administrativo."},
    ]},
    {"versao": "0.26.0", "data": "2026-09-06", "itens": [
        {"para": "admin", "titulo": "Lotes de entrega",
         "texto": "Na página Lotes, até 5 artigos prontos da mesma revista e do mesmo volume/número viram um só pacote (.zip com uma pasta, "
                  "um xpm.html) e um só aviso por e-mail com \"Total de XMLs = N\", como a SPS 1.10 pede. Depositar marca todos como entregues."},
    ]},
    {"versao": "0.25.0", "data": "2026-09-06", "itens": [
        {"para": "todos", "titulo": "Menu do topo mais limpo",
         "texto": "Com o menu no topo, Como funciona e Novidades viram ícones com dica, e a barra deixa de rolar."},
        {"para": "todos", "titulo": "Caixa do ISSN some ao escolher a revista",
         "texto": "No envio, o campo \"ISSN da revista\" só aparece com \"Detectar pelo ISSN\"; escolhida uma revista da lista, ele some."},
        {"para": "todos", "titulo": "Como funciona explica contas, organizações e revistas",
         "texto": "Nova seção com o que é conta, papel, organização e revista, como entrar numa organização e o que muda para quem está nela."},
        {"para": "admin", "titulo": "Organização em todo lugar",
         "texto": "Filtro por organização em Documentos, coluna em Usuários, membros na página Organizações, \"Quem vê esta revista\" ao "
                  "editar uma revista e \"Reexibir novidades\" para uma conta. O ISSN de uma revista de outra organização não é cadastrado "
                  "de novo: o sistema orienta a pedir ao administrador."},
    ]},
    {"versao": "0.24.0", "data": "2026-09-06", "itens": [
        {"para": "todos", "titulo": "Organizações: sua equipe vê os mesmos documentos",
         "texto": "Uma editora ou instituição agrupa contas: quem está na mesma organização vê os mesmos documentos e revistas. "
                  "Em Minha conta, crie a sua ou entre com o código de convite de um colega; ao criar conta também dá."},
        {"para": "admin", "titulo": "Administração de organizações",
         "texto": "Página Organizações (criar, renomear, novo código de convite, remover) e vínculo da conta em Usuários."},
    ]},
    {"versao": "0.23.0", "data": "2026-09-06", "itens": [
        {"para": "todos", "titulo": "PDF escaneado passa a ser lido por OCR",
         "texto": "Arquivo só com imagem é reconhecido por OCR (português e inglês) e segue o fluxo normal; o resultado avisa que o "
                  "texto veio do OCR e pede conferência. O visualizador também ganha a camada de texto."},
    ]},
    {"versao": "0.22.0", "data": "2026-09-06", "itens": [
        {"para": "todos", "titulo": "Envio em lote com fila de processamento",
         "texto": "Escolha vários PDF ou DOCX de uma vez (até 20): eles entram numa fila e são processados um a um. A lista de "
                  "documentos mostra \"na fila\", \"processando\" e o resultado, atualizando sozinha. Um arquivo só continua "
                  "sendo processado na hora."},
    ]},
    {"versao": "0.21.1", "data": "2026-09-06", "itens": [
        {"para": "todos", "titulo": "Bolinha no sino",
         "texto": "Enquanto houver novidade que você não viu, o sino \"Novidades\" mostra uma bolinha; ela some quando você abre a página."},
    ]},
    {"versao": "0.21.0", "data": "2026-09-06", "itens": [
        {"para": "todos", "titulo": "Novidades e notificações",
         "texto": "Depois de uma atualização, uma janela mostra o que mudou para você ao entrar. O sino \"Novidades\" no menu "
                  "leva à página com o histórico de versões e conta o que você ainda não viu."},
    ]},
    {"versao": "0.20.1", "data": "2026-09-06", "itens": [
        {"para": "todos", "titulo": "PDF escaneado é reconhecido",
         "texto": "Arquivo só com imagem, sem camada de texto, passa a ser avisado com clareza: o resultado pede o DOCX ou o PDF "
                  "gerado pelo editor, em vez de listar \"título não identificado\"."},
        {"para": "todos", "titulo": "Roteiro para depositar sozinho",
         "texto": "A tela de entrega explica, passo a passo, como a revista deposita o pacote no FTP da SciELO por conta própria "
                  "e que e-mail mandar."},
        {"para": "admin", "titulo": "Correções à mão por artigo",
         "texto": "O painel mostra a média de campos corrigidos à mão por artigo, que é a taxa de erro do motor."},
    ]},
    {"versao": "0.20.0", "data": "2026-09-06", "itens": [
        {"para": "todos", "titulo": "SciELO PS 1.10 é a versão padrão",
         "texto": "O XML sai na versão vigente da SPS e é validado no Schematron 1.10. A 1.9 continua disponível na tela de envio."},
        {"para": "todos", "titulo": "Pacote no formato da SPS 1.10",
         "texto": "O .zip traz uma pasta com o nome do pacote, o relatório xpm.html e, em publicação contínua, o número do lote. "
                  "O aviso de entrega segue o título e o texto fixos da SciELO."},
        {"para": "todos", "titulo": "Ir para o campo",
         "texto": "No resultado, cada bloqueante tem um link que abre a revisão já no campo que falta."},
        {"para": "todos", "titulo": "XML marcado como rascunho",
         "texto": "Enquanto houver bloqueante, o XML e o pacote saem marcados como rascunho, para ninguém entregar por engano."},
        {"para": "todos", "titulo": "Etapas com os nomes da SciELO",
         "texto": "\"Entrega confirmada\" e \"Correção pedida pela SciELO\" entraram na lista de etapas, como nos e-mails dela."},
        {"para": "todos", "titulo": "E-mail da equipe editorial",
         "texto": "O cadastro da revista ganhou o e-mail da equipe editorial, que entra em cópia no aviso de entrega."},
        {"para": "todos", "titulo": "Site não trava durante o processamento",
         "texto": "Enviar um artigo deixou de segurar as outras telas enquanto ele é lido e validado."},
        {"para": "admin", "titulo": "FTP: tipo de conta e sigla da coleção",
         "texto": "Configurações permitem escolher entre conta de prestador (Entrega na raiz) e conta da revista (acrônimo/Entrega), "
                  "e a sigla da coleção que vai no título do e-mail."},
        {"para": "admin", "titulo": "Tempo médio por artigo",
         "texto": "O painel mede quanto tempo o motor leva por artigo e mostra a média."},
        {"para": "admin", "titulo": "Freio de tentativas",
         "texto": "Dez senhas erradas em 15 minutos, por IP ou por e-mail, travam o login por 15 minutos; cinco contas novas por IP "
                  "no mesmo período também."},
    ]},
    {"versao": "0.19.0", "data": "2026-09-06", "itens": [
        {"para": "todos", "titulo": "Última abertura e ordenação",
         "texto": "A lista de documentos mostra quando cada um foi aberto pela última vez e pode ser ordenada, inclusive por "
                  "\"aberto mais recente\"."},
    ]},
    {"versao": "0.18.0", "data": "2026-09-06", "itens": [
        {"para": "todos", "titulo": "Contagem de páginas",
         "texto": "O total de páginas do arquivo vira page-count no XML e pode ser ajustado na revisão."},
        {"para": "todos", "titulo": "Declarações em três idiomas",
         "texto": "Agradecimentos, uso de IA, conflito de interesses, financiamento e \"como citar\" são reconhecidos em português, "
                  "inglês e espanhol."},
        {"para": "todos", "titulo": "Datas da caixa editorial",
         "texto": "\"Recebido: 23/12/24\", com ano de dois dígitos, passa a ser lido."},
        {"para": "todos", "titulo": "DOCX na tela de envio",
         "texto": "A tela de envio aceita DOCX. As imagens aparecem na prévia e há um botão de voltar ao topo."},
    ]},
    {"versao": "0.17.0", "data": "2026-09-05", "itens": [
        {"para": "todos", "titulo": "Referências mais fiéis",
         "texto": "\"(eds.)\" e \"(org.)\" viram editor, a data de acesso só sai com endereço, o rodapé da revista não gruda na "
                  "última referência, e referência sem chamada no texto vira aviso."},
    ]},
    {"versao": "0.16.0", "data": "2026-09-05", "itens": [
        {"para": "todos", "titulo": "Declarações editoriais",
         "texto": "Agradecimentos, financiamento, contribuição dos autores, disponibilidade de dados, conflito de interesses, uso "
                  "de IA e \"como citar\" na revisão, no lugar em que a SciELO publica cada um."},
        {"para": "todos", "titulo": "Editor-chefe no cadastro da revista",
         "texto": "Nome, ORCID e Lattes do editor; qualquer conta pode cadastrar revista. O que o sistema preenche sozinho aparece "
                  "em azul."},
    ]},
    {"versao": "0.15.0", "data": "2026-09-05", "itens": [
        {"para": "todos", "titulo": "Texto das seções editável",
         "texto": "Cada seção do corpo pode ser corrigida, e tabelas, figuras, equações, quadros e diálogos são inseridos no ponto "
                  "exato do texto."},
        {"para": "todos", "titulo": "Revista preenche o que é dela",
         "texto": "Vincular a revista preenche licença, seção e idioma a partir do cadastro."},
    ]},
    {"versao": "0.14.0", "data": "2026-09-05", "itens": [
        {"para": "todos", "titulo": "Entrada por DOCX",
         "texto": "Seções, tabelas e fórmulas do Word (OMML) vêm do próprio arquivo, sem adivinhação."},
        {"para": "todos", "titulo": "Ferramentas na revisão",
         "texto": "Busca no documento, completar pelo DOI (Crossref), conferir ORCID, CRediT por autor, financiamento e prévia de "
                  "como a SciELO publica."},
    ]},
    {"versao": "0.11.0", "data": "2026-09-05", "itens": [
        {"para": "todos", "titulo": "ISSN, visualizador e entrega",
         "texto": "Cadastro de revista pelo ISSN, arquivo original ao lado do formulário com seleção que preenche campos, anexos "
                  "criados à mão e tela de entrega à SciELO."},
    ]},
]
ATUAL = VERSOES[0]["versao"]
# quem vê cada público: o cliente só o que é de todos; o operador o que é de todos e de operador; o administrador tudo
QUEM_VE = {"todos": {"cliente", "operador", "admin"}, "operador": {"operador", "admin"}, "admin": {"admin"}}


def chave(versao: str) -> tuple:
    return tuple(int(x) for x in str(versao).split("."))


PALAVRAS_DE_ADMIN = ("administrador", "administra", "configurações", "correio", "painel", "usuários", "organizações (menu)")


def _confere():
    for v in VERSOES:
        for i in v["itens"]:
            if i.get("para") == "todos":
                texto = (i.get("titulo", "") + " " + i.get("texto", "")).lower()
                for p in PALAVRAS_DE_ADMIN:
                    if p in texto:
                        raise RuntimeError(f"app/novidades.py: item para 'todos' na versão {v['versao']} fala de administração ('{p}')")
    chaves = [chave(v["versao"]) for v in VERSOES]
    if chaves != sorted(chaves, reverse=True) or len(set(chaves)) != len(chaves):
        raise RuntimeError("app/novidades.py: versões fora de ordem ou repetidas")
    for v in VERSOES:
        for i in v["itens"]:
            if i.get("para") not in QUEM_VE or not i.get("titulo") or not i.get("texto"):
                raise RuntimeError(f"app/novidades.py: item mal formado na versão {v['versao']}")


_confere()


def _data_br(d: str) -> str:
    return f"{d[8:10]}/{d[5:7]}/{d[:4]}" if len(d) >= 10 else d


def visiveis(papel: str) -> List[dict]:
    """Versões com os itens que este papel pode ver; versão sem item visível some da lista."""
    saida = []
    for v in VERSOES:
        itens = [i for i in v["itens"] if papel in QUEM_VE.get(i["para"], set())]
        if itens:
            saida.append({"versao": v["versao"], "data": v["data"], "data_br": _data_br(v["data"]), "itens": itens})
    return saida


def linha_de_base(usuario: Optional[dict]) -> Optional[str]:
    """Última versão que a pessoa já viu. None quer dizer que tudo é novidade."""
    if not usuario or usuario.get("id") in ("local", "api"):
        return ATUAL  # modo local e scripts não têm conta: nada a mostrar
    vista = usuario.get("novidades_vistas")
    if vista:
        return str(vista)
    # conta de antes deste recurso: o que saiu antes do último acesso (ou da criação da conta) não é novidade
    ref = ((usuario.get("atividade") or {}).get("ultimo_acesso") or usuario.get("criado_em") or "")[:10]
    if not ref:
        return ATUAL
    anteriores = [v["versao"] for v in VERSOES if v["data"] < ref]
    return max(anteriores, key=chave) if anteriores else None


def pendentes(usuario: Optional[dict]) -> List[dict]:
    """Versões visíveis para o papel da pessoa e mais novas do que a última que ela viu."""
    base = linha_de_base(usuario)
    papel = (usuario or {}).get("papel") or "cliente"
    return [v for v in visiveis(papel) if base is None or chave(v["versao"]) > chave(base)]


def conta_itens(versoes: List[dict]) -> int:
    return sum(len(v["itens"]) for v in versoes or [])
