"""
Cliente minimo da API do Dokploy (v0.29) para os tres paineis (PROD, BD, HOMOL).
Le URLs e tokens de .env.deploy (gitignored). Rotas no formato /api/<router>.<procedure>;
GET para consultas (query string), POST com JSON para mutacoes. Header: x-api-key.

Uso como biblioteca:
    from ops.dokploy import Dokploy
    d = Dokploy("HOMOL"); d.get("project.all"); d.post("application.create", {...})
Uso na linha de comando (so leitura):
    python ops/dokploy.py HOMOL project.all
"""
import json
import os
import sys
import urllib.parse
import urllib.request

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def carrega_env(caminho=os.path.join(RAIZ, ".env.deploy")):
    env = {}
    with open(caminho, encoding="utf-8") as f:
        for linha in f:
            linha = linha.strip()
            if linha and not linha.startswith("#") and "=" in linha:
                k, v = linha.split("=", 1)
                env[k.strip()] = v.strip()
    return env


class Dokploy:
    def __init__(self, servidor="HOMOL"):
        env = carrega_env()
        self.servidor = servidor
        self.base = env[f"DOKPLOY_{servidor}_URL"].rstrip("/")
        self.token = env[f"DOKPLOY_{servidor}_TOKEN"]

    def _req(self, metodo, rota, dados=None, params=None):
        url = f"{self.base}/api/{rota}"
        if params:
            url += "?" + urllib.parse.urlencode(params)
        corpo = json.dumps(dados).encode("utf-8") if dados is not None else None
        req = urllib.request.Request(url, data=corpo, method=metodo, headers={
            "x-api-key": self.token, "Accept": "application/json", "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                b = r.read()
                return json.loads(b) if b else None
        except urllib.error.HTTPError as e:
            detalhe = e.read().decode("utf-8", "ignore")
            raise RuntimeError(f"{metodo} {rota} -> HTTP {e.code}: {detalhe[:600]}") from None

    def get(self, rota, **params):
        return self._req("GET", rota, params=params or None)

    def post(self, rota, dados):
        return self._req("POST", rota, dados=dados)


if __name__ == "__main__":
    srv, rota = sys.argv[1], sys.argv[2]
    params = dict(a.split("=", 1) for a in sys.argv[3:])
    print(json.dumps(Dokploy(srv).get(rota, **params), ensure_ascii=False, indent=2)[:6000])
