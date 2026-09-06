"""ArticleModel da PoC: espelho simplificado do JATS, com proveniencia por campo."""
from dataclasses import dataclass, field, asdict
from typing import List, Optional


@dataclass
class Titulo:
    texto: str
    idioma: Optional[str] = None
    tipo: str = "article-title"  # article-title | trans-title
    pagina: int = 1


@dataclass
class Afiliacao:
    id: str
    texto_original: str
    instituicao: Optional[str] = None
    divisao: Optional[str] = None
    cidade: Optional[str] = None
    estado: Optional[str] = None
    pais: Optional[str] = None
    pais_iso: Optional[str] = None
    origem: str = "desconhecida"  # linha estruturada | nota biografica | lateral
    confianca: str = "baixa"


@dataclass
class Autor:
    nome_completo: str
    sobrenome: str
    nomes: str
    marcadores: List[str] = field(default_factory=list)
    orcid: Optional[str] = None
    orcid_valido: Optional[bool] = None
    email: Optional[str] = None
    lattes: Optional[str] = None
    aff_ids: List[str] = field(default_factory=list)
    bio: Optional[str] = None
    correspondente: bool = False
    papel: str = "author"


@dataclass
class Resumo:
    idioma: Optional[str]
    rotulo: str
    texto: str
    palavras_chave: List[str] = field(default_factory=list)
    rotulo_palavras: Optional[str] = None


@dataclass
class Secao:
    titulo: str
    nivel: int = 1
    numero: Optional[str] = None
    titulo_completo: Optional[str] = None  # como aparece no PDF (ex.: "1. Introdução")
    sec_type: Optional[str] = None
    pagina: int = 1
    paragrafos: List[str] = field(default_factory=list)


@dataclass
class Citacao:
    autor: str
    ano: str
    texto: str
    ref_index: Optional[int] = None


@dataclass
class Nota:
    id: str
    rotulo: str
    texto: str
    pagina: int
    tipo: str = "other"
    chamada_no_texto: bool = False
    ligada_a: Optional[str] = None  # 'autor:1' | 'titulo' | None


@dataclass
class Figura:
    tipo: str  # fig | table
    rotulo: str
    legenda: str
    fonte: Optional[str] = None
    pagina: int = 1
    chamada_no_texto: bool = False
    numero: Optional[str] = None          # "1" em "Figura 1"
    secao_indice: Optional[int] = None    # indice da secao em model.secoes onde a legenda apareceu
    pos_paragrafo: Optional[int] = None   # numero de paragrafos da secao antes da legenda
    imagem_indice: Optional[int] = None   # indice em Documento.imagens
    arquivo: Optional[str] = None         # nome do arquivo salvo (ex.: fig01.jpeg)
    ext: Optional[str] = None
    largura: Optional[int] = None
    altura: Optional[int] = None


@dataclass
class Tabela:
    """Tabela detectada no PDF: grade de celulas + legenda casada pelo rotulo."""
    numero: Optional[str] = None            # "1" em "Tabela 1"
    rotulo: str = ""                        # "Tabela 1"
    legenda: str = ""
    fonte: Optional[str] = None             # "Fonte: ..."
    pagina: int = 1
    celulas: List[List[str]] = field(default_factory=list)
    linhas_cabecalho: int = 0
    colunas: int = 0
    chamada_no_texto: bool = False
    secao_indice: Optional[int] = None
    pos_paragrafo: Optional[int] = None
    bbox: List[float] = field(default_factory=list)
    qualidade: str = "alta"                 # alta (grade com linhas) | media | baixa (colunas incertas -> vai como imagem)
    arquivo: Optional[str] = None           # tabNN.png quando a grade nao e confiavel
    largura: Optional[int] = None
    altura: Optional[int] = None


@dataclass
class Equacao:
    """Equacao destacada. No PDF sai como imagem recortada e o MathML e escrito na revisao (em LaTeX);
    no DOCX o Word ja guarda a formula em OMML, que vira MathML sem ninguem digitar."""
    numero: Optional[str] = None            # "12" em "(12)"
    rotulo: Optional[str] = None            # "(12)"
    texto: str = ""                         # texto bruto, para conferencia
    pagina: int = 1
    numerada: bool = False
    chamada_no_texto: bool = False
    secao_indice: Optional[int] = None
    pos_paragrafo: Optional[int] = None
    arquivo: Optional[str] = None           # eq01.png gravado pelo extrator
    largura: Optional[int] = None
    altura: Optional[int] = None
    bbox: List[float] = field(default_factory=list)
    latex: str = ""                         # escrito na revisao; a SciELO exige MathML ou LaTeX
    mathml: Optional[str] = None            # gerado do LaTeX, ou convertido do OMML do Word
    erro_mathml: Optional[str] = None


@dataclass
class Referencia:
    texto: str
    tipo: str = "other"
    autores: List[str] = field(default_factory=list)
    ano: Optional[str] = None
    doi: Optional[str] = None
    url: Optional[str] = None
    citada: bool = False


@dataclass
class Datas:
    recebido: Optional[str] = None
    revisado: Optional[str] = None
    aceito: Optional[str] = None
    publicado: Optional[str] = None
    origem: Optional[str] = None


@dataclass
class ArticleModel:
    arquivo: str
    paginas: int = 0
    gerado_por: Optional[str] = None
    fonte_corpo_pt: float = 0.0
    layout: str = "uma coluna"
    # revista
    revista_titulo: Optional[str] = None
    revista_abrev: Optional[str] = None
    issn: List[str] = field(default_factory=list)
    # artigo
    doi: Optional[str] = None
    outros_dois: List[str] = field(default_factory=list)
    heading: Optional[str] = None
    tipo_artigo: Optional[str] = None
    idioma: Optional[str] = None
    volume: Optional[str] = None
    numero: Optional[str] = None
    ano: Optional[str] = None
    elocation: Optional[str] = None
    fpage: Optional[str] = None
    lpage: Optional[str] = None
    titulos: List[Titulo] = field(default_factory=list)
    autores: List[Autor] = field(default_factory=list)
    editores: List[Autor] = field(default_factory=list)
    afiliacoes: List[Afiliacao] = field(default_factory=list)
    orcids_nao_atribuidos: List[dict] = field(default_factory=list)
    resumos: List[Resumo] = field(default_factory=list)
    datas: Datas = field(default_factory=Datas)
    licenca: Optional[str] = None
    licenca_url: Optional[str] = None
    secoes: List[Secao] = field(default_factory=list)
    citacoes: List[Citacao] = field(default_factory=list)
    notas: List[Nota] = field(default_factory=list)
    figuras: List[Figura] = field(default_factory=list)
    tabelas: List[Tabela] = field(default_factory=list)
    equacoes: List[Equacao] = field(default_factory=list)
    referencias: List[Referencia] = field(default_factory=list)
    estilo_referencias: Optional[str] = None
    cabecalhos: List[str] = field(default_factory=list)
    back_matter: List[dict] = field(default_factory=list)
    proveniencia: dict = field(default_factory=dict)
    avisos: List[str] = field(default_factory=list)
    sem_texto: bool = False  # PDF sem camada de texto (escaneado): o motor nao faz OCR; vira bloqueante no gerador

    def marca(self, campo, origem):
        self.proveniencia[campo] = origem

    def aviso(self, msg):
        if msg not in self.avisos:
            self.avisos.append(msg)

    def to_dict(self):
        return asdict(self)

    @property
    def titulo_principal(self):
        for t in self.titulos:
            if t.tipo == "article-title":
                return t.texto
        return None
