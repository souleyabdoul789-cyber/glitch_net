"""Surveillance réelle des services : le serveur contacte lui-même chaque site
(le navigateur ne peut pas lire l'état d'un autre site à cause de CORS).
Les adresses sont fixées ici, jamais fournies par un utilisateur."""
import asyncio, time, urllib.request, urllib.error

# Modifier ICI pour ajouter ou corriger un service surveillé.
SERVICES_SURVEILLES = [
    {"id": "pluton", "nom": "Pluton (serveur central et base de données)", "type": "base"},
    {"id": "site", "nom": "Site G-SOCIETY", "url": "https://g-society.onrender.com/index.html"},
    {"id": "grind-app", "nom": "GRIND (application)", "url": "https://grind-school-7agz.onrender.com"},
    {"id": "grind-serveur", "nom": "GRIND (serveur)", "url": "https://grind-4vsz.onrender.com"},
]
DELAI_MAX_S = 30        # un service Render en veille peut mettre ~30 s à se réveiller
SEUIL_LENT_MS = 4000
CACHE_S = 20

_cache = {"t": 0.0, "data": None}


def _ms(t0):
    return int((time.perf_counter() - t0) * 1000)


def sonder_url(url, delai=DELAI_MAX_S):
    """Une requête GET réelle. Tout code < 500 prouve que le service répond."""
    t0 = time.perf_counter()
    req = urllib.request.Request(url, headers={"User-Agent": "G-SOCIETY-Monitor/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=delai) as r:
            code = r.status
            r.read(512)
    except urllib.error.HTTPError as e:
        code = e.code
    except Exception as e:
        timeout = "timed out" in str(e).lower() or type(e).__name__ in ("TimeoutError", "timeout")
        return {"etat": "injoignable", "code": None, "ms": _ms(t0),
                "detail": "Aucune réponse en %d s (service peut-être en veille, réessayez)" % delai if timeout
                else "Connexion impossible"}
    ms = _ms(t0)
    if code >= 500:
        return {"etat": "panne", "code": code, "ms": ms, "detail": "Le service répond par une erreur serveur"}
    return {"etat": "lent" if ms > SEUIL_LENT_MS else "ok", "code": code, "ms": ms,
            "detail": "Réponse lente (réveil probable)" if ms > SEUIL_LENT_MS else "Répond normalement"}


def sonder_base(get_db):
    t0 = time.perf_counter()
    try:
        db = get_db()
        try:
            with db.cursor() as c:
                c.execute("SELECT 1")
                c.fetchone()
        finally:
            db.close()
    except Exception:
        return {"etat": "panne", "code": None, "ms": _ms(t0), "detail": "Base de données inaccessible"}
    ms = _ms(t0)
    return {"etat": "lent" if ms > SEUIL_LENT_MS else "ok", "code": None, "ms": ms, "detail": "Base de données joignable"}


async def verifier_services(get_db, force=False):
    now = time.time()
    if not force and _cache["data"] and now - _cache["t"] < CACHE_S:
        return _cache["data"]
    taches = [asyncio.to_thread(sonder_base, get_db) if s.get("type") == "base" else asyncio.to_thread(sonder_url, s["url"])
              for s in SERVICES_SURVEILLES]
    resultats = await asyncio.gather(*taches)
    data = {"verifie_a": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()),
            "services": [{"id": s["id"], "nom": s["nom"], **r} for s, r in zip(SERVICES_SURVEILLES, resultats)]}
    _cache.update(t=now, data=data)
    return data
