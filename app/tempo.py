"""
Fuso horario do sistema: America/Sao_Paulo (UTC-03:00), o horario de Brasilia.

Tudo que o sistema grava e mostra usa este fuso, mesmo quando o servidor roda em UTC (o container do Dokploy roda).
Datas antigas, gravadas sem fuso, sao lidas como UTC e convertidas — por isso `formata` aceita as duas formas.
"""
import datetime as dt

TZ = dt.timezone(dt.timedelta(hours=-3), "-03")
NOME_FUSO = "horário de Brasília (UTC-3)"


def agora() -> dt.datetime:
    return dt.datetime.now(TZ)


def agora_iso(segundos: bool = True) -> str:
    return agora().isoformat(timespec="seconds" if segundos else "minutes")


def le(valor) -> dt.datetime:
    """ISO -> datetime no fuso de Brasília. Sem fuso na string, assume UTC (gravações antigas do container)."""
    if not valor:
        return None
    try:
        d = dt.datetime.fromisoformat(str(valor))
    except ValueError:
        return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=dt.timezone.utc)
    return d.astimezone(TZ)


def formata(valor, com_hora: bool = True) -> str:
    d = le(valor)
    if not d:
        return "—"
    return d.strftime("%d/%m/%Y %H:%M" if com_hora else "%d/%m/%Y")


def ha_quanto(valor) -> str:
    """'agora', 'há 5 min', 'há 2 h', 'há 3 dias' — para a coluna de última atividade."""
    d = le(valor)
    if not d:
        return "nunca"
    seg = (agora() - d).total_seconds()
    if seg < 90:
        return "agora"
    if seg < 3600:
        return f"há {int(seg // 60)} min"
    if seg < 86400:
        return f"há {int(seg // 3600)} h"
    dias = int(seg // 86400)
    return "ontem" if dias == 1 else f"há {dias} dias"


def online(valor, minutos: int = 5) -> bool:
    d = le(valor)
    return bool(d and (agora() - d).total_seconds() <= minutos * 60)
