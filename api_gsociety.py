"""Routes HTTP de la plateforme G-SOCIETY (comptes, sessions, clés, annonces,
administration). Chaque route valide ses entrées, limite le débit, ferme sa
connexion à la base et ne révèle jamais de détail interne."""
from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from auth import (
    get_db, creer_compte_gsociety, login_gsociety, creer_session, verifier_session,
    supprimer_session, profil_gsociety, est_admin_gsociety, lister_comptes_gsociety,
    suspendre_compte_gsociety, reactiver_compte_gsociety, certifier_compte_gsociety,
    retirer_certification_gsociety, generer_api_key, verifier_api_key_identite,
    creer_post_service, lister_posts_service, creer_commentaire_post,
    lister_commentaires_post, noter_post,
)
from security import (
    limiteur, ip_client, valider_username, valider_mot_de_passe, url_https_valide,
    SERVICES, VERSION_RE, MSG_TROP_DE_REQUETES,
)

router = APIRouter()

SESSION_EXPIREE = "Session expirée, veuillez vous reconnecter"
ERR = lambda msg: {"success": False, "error": msg}


class _Db:
    """Ouvre une connexion et la ferme toujours, même en cas d'erreur."""
    def __enter__(self):
        self.db = get_db()
        return self.db
    def __exit__(self, *a):
        try:
            self.db.close()
        except Exception:
            pass
        return False


# ------------------------------------------------------------------
# Comptes
# ------------------------------------------------------------------
class CompteGSociety(BaseModel):
    username: str = Field(max_length=64)
    password: str = Field(max_length=200)


class InscriptionGSociety(CompteGSociety):
    avatar_id: int
    accept_cgu: bool = False


@router.post("/api/gsociety/signup")
async def api_gsociety_signup(data: InscriptionGSociety, request: Request):
    ip = ip_client(request)
    if not limiteur.autorise(f"signup:{ip}", 5, 3600):
        return ERR("Trop de comptes créés depuis cette connexion. Réessayez plus tard.")
    username = data.username.strip()
    if not data.accept_cgu:
        return ERR("Vous devez accepter les conditions d'utilisation.")
    msg = valider_username(username) or valider_mot_de_passe(data.password, username)
    if msg:
        return ERR(msg)
    if not 1 <= data.avatar_id <= 20:
        return ERR("Avatar invalide.")
    with _Db() as db:
        gid = creer_compte_gsociety(username, data.password, data.avatar_id, db)
        if gid is None:
            return ERR("Ce nom de compte est déjà pris")
        token = creer_session(gid, db)
    # Le compte est créé ET connecté : le site peut rediriger directement.
    return {"success": True, "message": "Compte créé", "username": username,
            "avatar_id": data.avatar_id, "session_token": token, "verified": False, "is_admin": False}


@router.post("/api/gsociety/login")
async def api_gsociety_login(data: CompteGSociety, request: Request):
    ip = ip_client(request)
    cle_compte = f"echec:{data.username.strip().lower()}"
    if not limiteur.autorise(f"login:{ip}", 30, 600) or limiteur.compte(cle_compte, 900) >= 5:
        return ERR(MSG_TROP_DE_REQUETES)
    with _Db() as db:
        req = login_gsociety(data.username.strip(), data.password, db)
        if req is None:
            limiteur.enregistre(cle_compte)
            return ERR("Identifiants incorrects")
        if req == "suspendu":
            return ERR("Ce compte est suspendu. Consultez « À propos des bannissements » pour contester.")
        limiteur.oublie(cle_compte)
        token = creer_session(req[0], db)
        profil = profil_gsociety(req[0], db) or {}
    return {"success": True, "message": "Connexion réussie", "username": req[1], "avatar_id": req[3],
            "session_token": token, "verified": profil.get("verified", False), "is_admin": profil.get("is_admin", False)}


class SessionOnly(BaseModel):
    session_token: str = Field(max_length=200)


@router.post("/api/gsociety/me")
async def api_gsociety_me(data: SessionOnly, request: Request):
    """Valide la session et renvoie le profil à jour (badge, droits)."""
    if not limiteur.autorise(f"me:{ip_client(request)}", 120, 60):
        return ERR(MSG_TROP_DE_REQUETES)
    with _Db() as db:
        s = verifier_session(data.session_token, db)
        if s is None:
            return ERR(SESSION_EXPIREE)
        profil = profil_gsociety(s[0], db)
    return {"success": True, **profil}


@router.post("/api/gsociety/logout")
async def api_gsociety_logout(data: SessionOnly):
    with _Db() as db:
        supprimer_session(data.session_token, db)
    return {"success": True}


# ------------------------------------------------------------------
# Clés API
# ------------------------------------------------------------------
class DemandeCleSession(BaseModel):
    session_token: str = Field(max_length=200)
    categorie: str = Field(default="glitch", max_length=20)
    duree_jours: int = 90


@router.post("/api/session/request-key")
async def api_session_request_key(data: DemandeCleSession, request: Request):
    if not limiteur.autorise(f"cle:{ip_client(request)}", 10, 3600):
        return ERR(MSG_TROP_DE_REQUETES)
    with _Db() as db:
        session = verifier_session(data.session_token, db)
        if session is None:
            return ERR(SESSION_EXPIREE)
        r = generer_api_key(session[1], db, categorie=data.categorie, duree_jours=data.duree_jours)
    if not r["ok"]:
        return ERR(r["error"])
    return {"success": True, "api_key": r["api_key"], "categorie": r["categorie"], "expires_in_days": r["expires_in_days"]}


class VerifKeyRequest(BaseModel):
    api_key: str = Field(max_length=200)
    categorie: str = Field(max_length=20)


@router.post("/api/verify-key")
async def api_verify_key(data: VerifKeyRequest, request: Request):
    """Pour les services externes (GRIND…) : renvoie l'identité réelle liée à la clé."""
    if not limiteur.autorise(f"verify:{ip_client(request)}", 120, 60):
        return {"valid": False, "username": None}
    with _Db() as db:
        username = verifier_api_key_identite(data.api_key, db, categorie_attendue=data.categorie)
    return {"valid": username is not None, "username": username}


# ------------------------------------------------------------------
# Annonces / releases
# ------------------------------------------------------------------
class NouveauPost(BaseModel):
    session_token: str = Field(max_length=200)
    service: str = Field(max_length=20)
    type: str = Field(max_length=20)
    title: str = Field(max_length=300)
    body: str = Field(max_length=6000)
    version: str | None = Field(default=None, max_length=40)
    apk_link: str | None = Field(default=None, max_length=600)


@router.post("/api/posts/create")
async def api_posts_create(data: NouveauPost, request: Request):
    if not limiteur.autorise(f"post:{ip_client(request)}", 30, 3600):
        return ERR(MSG_TROP_DE_REQUETES)
    title, body = data.title.strip(), data.body.strip()
    version = (data.version or "").strip() or None
    apk_link = (data.apk_link or "").strip() or None
    with _Db() as db:
        admin = est_admin_gsociety(data.session_token, db)
        if admin is None:
            return ERR("Accès refusé")
        if data.type not in ("annonce", "release"):
            return ERR("Type invalide")
        if data.service not in SERVICES:
            return ERR("Service inconnu")
        if not title or not body:
            return ERR("Titre et message requis")
        if len(title) > 150:
            return ERR("Titre trop long (150 caractères maximum)")
        if data.type == "release":
            if not version or not VERSION_RE.match(version):
                return ERR("Numéro de version invalide (ex : 1.2.0)")
            if not apk_link or not url_https_valide(apk_link):
                return ERR("Le lien de téléchargement doit commencer par https://")
        else:
            version = apk_link = None
        ok = creer_post_service(data.service, data.type, admin[1], title, body, db, version=version, apk_link=apk_link)
    return {"success": bool(ok)}


class ListePosts(BaseModel):
    service: str = Field(max_length=20)


@router.post("/api/posts/list")
async def api_posts_list(data: ListePosts, request: Request):
    if not limiteur.autorise(f"plist:{ip_client(request)}", 120, 60):
        return ERR(MSG_TROP_DE_REQUETES)
    if data.service not in SERVICES:
        return {"success": True, "posts": []}
    with _Db() as db:
        rows = lister_posts_service(data.service, db)
    posts = [{
        "id": r[0], "type": r[1], "title": r[2], "body": r[3], "version": r[4], "apk_link": r[5],
        "created_at": str(r[6]), "admin_username": r[7], "admin_verified": bool(r[8]),
        "note_moyenne": round(float(r[9]), 1) if r[9] is not None else None, "nb_notes": r[10],
    } for r in rows]
    return {"success": True, "posts": posts}


class NouveauCommentaire(BaseModel):
    session_token: str = Field(max_length=200)
    post_id: int
    comment: str = Field(max_length=2000)


@router.post("/api/posts/comment")
async def api_posts_comment(data: NouveauCommentaire):
    comment = data.comment.strip()
    if not comment:
        return ERR("Commentaire vide")
    if len(comment) > 500:
        return ERR("Commentaire trop long (500 caractères maximum)")
    with _Db() as db:
        session = verifier_session(data.session_token, db)
        if session is None:
            return ERR(SESSION_EXPIREE)
        if not limiteur.autorise(f"comment:{session[0]}", 10, 60):
            return ERR("Doucement : réessayez dans une minute.")
        ok = creer_commentaire_post(data.post_id, session[1], comment, db)
    return {"success": bool(ok)}


class ListeCommentaires(BaseModel):
    post_id: int


@router.post("/api/posts/comments")
async def api_posts_comments(data: ListeCommentaires, request: Request):
    if not limiteur.autorise(f"clist:{ip_client(request)}", 120, 60):
        return ERR(MSG_TROP_DE_REQUETES)
    with _Db() as db:
        rows = lister_commentaires_post(data.post_id, db)
    return {"success": True, "comments": [
        {"comment": r[0], "created_at": str(r[1]), "username": r[2], "verified": bool(r[3])} for r in rows]}


class NoterPost(BaseModel):
    session_token: str = Field(max_length=200)
    post_id: int
    stars: int


@router.post("/api/posts/rate")
async def api_posts_rate(data: NoterPost):
    if not 1 <= data.stars <= 5:
        return ERR("Note invalide")
    with _Db() as db:
        session = verifier_session(data.session_token, db)
        if session is None:
            return ERR(SESSION_EXPIREE)
        if not limiteur.autorise(f"rate:{session[0]}", 30, 60):
            return ERR("Doucement : réessayez dans une minute.")
        ok = noter_post(data.post_id, session[1], data.stars, db)
    return {"success": bool(ok)}


# ------------------------------------------------------------------
# Administration — toute route vérifie d'abord que la session est admin
# ------------------------------------------------------------------
@router.post("/api/admin/verify")
async def api_admin_verify(data: SessionOnly, request: Request):
    if not limiteur.autorise(f"adm:{ip_client(request)}", 60, 60):
        return {"is_admin": False}
    with _Db() as db:
        return {"is_admin": est_admin_gsociety(data.session_token, db) is not None}


@router.post("/api/admin/accounts")
async def api_admin_accounts(data: SessionOnly):
    with _Db() as db:
        if est_admin_gsociety(data.session_token, db) is None:
            return ERR("Accès refusé")
        rows = lister_comptes_gsociety(db)
    return {"success": True, "comptes": [
        {"id": r[0], "username": r[1], "avatar_id": r[2], "is_admin": bool(r[3]), "badge": r[4],
         "verified": bool(r[3] or r[4]), "created_at": str(r[5]), "nb_cles": r[6], "suspended": r[7] is not None}
        for r in rows]}


class ActionCompte(BaseModel):
    session_token: str = Field(max_length=200)
    username: str = Field(max_length=64)


def _action_admin(data: ActionCompte, fonction, ok_msg: str):
    with _Db() as db:
        admin = est_admin_gsociety(data.session_token, db)
        if admin is None:
            return ERR("Accès refusé")
        if fonction is suspendre_compte_gsociety and data.username.lower() == admin[1].lower():
            return ERR("Vous ne pouvez pas vous suspendre vous-même.")
        r = fonction(data.username, db)
    if r == "admin":
        return ERR("Un administrateur ne peut pas être suspendu.")
    return {"success": bool(r), "message": ok_msg.format(u=data.username) if r else "Compte introuvable"}


@router.post("/api/admin/suspend")
async def api_admin_suspend(data: ActionCompte):
    return _action_admin(data, suspendre_compte_gsociety, "{u} suspendu (sessions et clés révoquées)")


@router.post("/api/admin/unsuspend")
async def api_admin_unsuspend(data: ActionCompte):
    return _action_admin(data, reactiver_compte_gsociety, "{u} réactivé")


@router.post("/api/admin/certify")
async def api_admin_certify(data: ActionCompte):
    return _action_admin(data, certifier_compte_gsociety, "{u} certifié")


@router.post("/api/admin/uncertify")
async def api_admin_uncertify(data: ActionCompte):
    return _action_admin(data, retirer_certification_gsociety, "Certification retirée à {u}")
