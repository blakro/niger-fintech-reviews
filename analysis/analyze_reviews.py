"""Analyse des avis Google Play — Mobile Money & Banques au Niger.

Entrée  : data/all_playstore_reviews.csv  (produit par notebooks/scrape_playstore_reviews.ipynb)
Sorties : data/reviews_clean.csv          un avis par ligne, enrichi (thèmes, sentiment, longueur…)
          analysis/aggregates.json        tous les indicateurs calculés
          docs/data.js                    les mêmes indicateurs, lus par le dashboard (docs/index.html)

Usage   : python analysis/analyze_reviews.py

Le script est organisé en 5 étapes :
  1. Paramètres            — les réglages de l'analyse, modifiables en un seul endroit
  2. Chargement/nettoyage  — lecture du fichier brut, normalisation du texte
  3. Thèmes                — détection des sujets abordés par mots-clés (+ auto-test du lexique)
  4. Indicateurs           — notes, classements, tendances, versions, réponses des éditeurs…
  5. Export                — écriture des fichiers de sortie
"""
from __future__ import annotations

import json
import math
import re
import unicodedata
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent

# ─────────────────────────────────────────────────────────────────────────────
# 1. PARAMÈTRES
# ─────────────────────────────────────────────────────────────────────────────
CAP_PER_APP = 5000          # plafond de collecte (cf. notebook) : une app à 5 000 avis est « tronquée »
MIN_REVIEWS_RANKING = 100   # en dessous, l'app n'entre pas dans le classement principal
PRIOR_WEIGHT = 50           # note ajustée : chaque app « démarre » avec 50 avis à la note moyenne du secteur
MIN_REVIEWS_WINDOW = 30     # nb d'avis minimum pour publier une note sur une sous-période
TREND_MONTHS = 6            # tendance : 6 derniers mois vs 6 mois précédents
MIN_VERSION_REVIEWS = 40    # une version d'app doit réunir ≥ 40 avis pour être analysée
MIN_NEG_FOR_MATRIX = 50     # une app doit avoir ≥ 50 avis négatifs pour figurer dans la matrice app × thème
SHORT_REVIEW_WORDS = 3      # un avis de ≤ 3 mots (« top », « très bien ») est considéré comme « court »
MONTHLY_SINCE = "2023-01-01"
APP_TRENDS_SINCE = "2024-01-01"

BANKS = {"Ecobank Mobile", "MyBOA", "BIA Niger Mobile", "My KEAZ (Orabank)", "BSIC NET",
         "Atlantique Mobile", "BAGRINET", "BIN MOBILE", "BHN Mobile"}

# ─────────────────────────────────────────────────────────────────────────────
# LEXIQUE DES THÈMES (utilisé à l'étape 3)
#    Le texte est d'abord mis en minuscules et débarrassé de ses accents
#    (« Mise à jour » → « mise a jour »), puis chaque expression est cherchée
#    comme MOT ENTIER : « lent » ne correspond plus à « excellent », « cher » ne
#    correspond plus à « chercher » ou « marcher » (bugs de la version précédente).
#    \w* = « n'importe quelle fin de mot » (connect\w* → connecter, connexion…)
# ─────────────────────────────────────────────────────────────────────────────
THEMES: dict[str, list[str]] = {
    "Connexion / Accès": [
        r"connexion", r"(?:de)?connect\w*", r"log ?in", r"otp", r"mot de passe", r"password", r"mdp",
        r"codes?", r"pin", r"authentifi\w*", r"identifiants?", r"acceder", r"acces",
        r"(?:de)?verrouill\w*", r"(?:de)?bloqu\w*", r"biometri\w*", r"empreinte\w*",
        r"change\w* (?:de |mon |d')?(?:telephone|portable|appareil|numero|sim|puce)",
        r"(?:n'arrive|arrive) (?:pas|plus) a (?:me |m')?(?:connect\w*|acceder|entrer)",
    ],
    "Inscription / Activation": [
        r"inscri\w*", r"enregistr\w*", r"enrol\w*", r"enroul\w*",
        r"cre\w* (?:un |mon |de |le )?compte", r"creation (?:de |du )?compte", r"ouvr\w* (?:un )?compte",
        r"activ(?:er|ation|e)", r"kyc", r"piece d'identite", r"carte d'identite", r"selfie", r"profil",
    ],
    "Bugs / Plantages": [
        r"bug\w*", r"beug\w*", r"crash\w*", r"plant\w*", r"erreur\w*", r"error",
        r"ne (?:marche|fonctionne|s'ouvre|repond) (?:pas|plus)", r"(?:marche|fonctionne|s'ouvre) (?:pas|plus)",
        r"(?:pas|plus|non) fonctionnel\w*", r"(?:dys|dis)fonction\w*",
        r"(?:n'arrive|arrive) (?:pas|plus|jamais) a (?:l'|s')?ouvrir",
        r"ferme (?:toute )?seule?", r"page blanche", r"ecran (?:blanc|noir)", r"panne\w*",
        r"maintenance", r"reessayer plus tard",
    ],
    "Mise à jour / Installation": [
        r"mises? a jour", r"mettre a jour", r"update\w*", r"(?:nouvelle|ancienne|derniere) version", r"version",
        r"(?:re)?install\w*", r"desinstall\w*", r"telecharg\w*",
    ],
    "Transactions / Argent": [
        r"transfert\w*", r"transferer", r"transactions?", r"retraits?", r"retir\w*", r"depots?", r"deposer",
        r"paiements?", r"payer", r"virements?", r"solde", r"argent", r"debit\w*", r"rembours\w*",
        r"credit\w*", r"recharg\w*", r"factur\w*", r"operations?", r"plafon\w*", r"deplafon\w*",
    ],
    "Carte bancaire": [
        r"cartes? (?:virtuelles?|visa|bancaires?|prepayees?|gim|gab)", r"visa", r"mastercard",
    ],
    "Frais / Tarifs": [
        r"frais", r"tarif\w*", r"commissions?", r"chers?", r"cheres?", r"couts?", r"couteu\w*",
        r"preleve\w*", r"prelevements?", r"gratuit\w*", r"taxes?", r"ponctions?",
    ],
    "Service client": [
        r"service clients?", r"service apres", r"support", r"assistance", r"customer (?:service|care)",
        r"conseill(?:er|ere)s?", r"gestionnaire", r"joindre", r"injoignable", r"contact\w*",
        r"reclamations?", r"aucune (?:aide|reponse|suite)", r"personne ne (?:repond|decroche)",
        r"sans (?:aucune )?(?:explications?|communication|reponse)", r"call ?center", r"centre d'appel",
        r"hotline", r"numero vert",
    ],
    "Lenteur / Réseau": [
        r"lente?s?", r"lenteurs?", r"lentement", r"slow", r"reseaux?", r"network", r"internet",
        r"chargement", r"charge pas", r"ne charge", r"tourne en rond", r"attente", r"attendre",
        r"timeout", r"delais?",
    ],
    "Sécurité / Fraude": [
        r"securi\w*", r"arnaqu\w*", r"escro\w*", r"fraud\w*", r"vol", r"vole", r"volee", r"voleurs?",
        r"pirat\w*", r"hack\w*", r"disparu\w*", r"disparition",
    ],
    "Facilité / Rapidité": [
        r"facile\w*", r"simple\w*", r"simplicite", r"pratique\w*", r"interface", r"design", r"intuiti\w*",
        r"ergonom\w*", r"rapide\w*", r"rapidite", r"fluide", r"efficace\w*", r"accessible",
    ],
}
POSITIVE_THEMES = {"Facilité / Rapidité"}   # thèmes « compliments » (exclus des irritants)

# Phrases témoins : le script s'arrête si le lexique ne les classe pas comme attendu.
# Ajoutez-en une à chaque fois que vous corrigez une erreur de classement.
LEXICON_TESTS = [
    ("Excellent application, je recommande", set(), {"Lenteur / Réseau"}),
    ("L'application est trop lente", {"Lenteur / Réseau"}, set()),
    ("Téléchargement rapide", {"Mise à jour / Installation", "Facilité / Rapidité"}, {"Lenteur / Réseau"}),
    ("Il faut chercher partout, ça ne veut pas marcher", set(), {"Frais / Tarifs"}),
    ("Les frais sont trop chers", {"Frais / Tarifs"}, set()),
    ("Je vous la conseille vivement", set(), {"Service client"}),
    ("Je n'arrive pas à me connecter, le code OTP n'arrive jamais", {"Connexion / Accès"}, set()),
    ("Mon compte est bloqué depuis une semaine", {"Connexion / Accès"}, set()),
    ("Depuis la mise à jour l'application plante", {"Mise à jour / Installation", "Bugs / Plantages"}, set()),
    ("Impossible de créer un compte", {"Inscription / Activation"}, set()),
    ("Il faut insérer la carte SIM", set(), {"Carte bancaire"}),
    ("Impossible de recharger ma carte virtuelle", {"Carte bancaire", "Transactions / Argent"}, set()),
    ("Service client injoignable", {"Service client"}, set()),
    ("On m'a volé mon argent, c'est une arnaque", {"Sécurité / Fraude", "Transactions / Argent"}, set()),
    ("Simple, facile et rapide", {"Facilité / Rapidité"}, set()),
]


def normalize(text: str) -> str:
    """minuscules, sans accents, apostrophes unifiées, espaces simples."""
    text = unicodedata.normalize("NFKD", str(text).lower().replace("’", "'"))
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", text).strip()


THEME_RE = {t: re.compile(r"\b(?:" + "|".join(alts) + r")\b") for t, alts in THEMES.items()}


def themes_of(text: str) -> set[str]:
    t = normalize(text)
    return {name for name, rx in THEME_RE.items() if rx.search(t)}


def check_lexicon() -> None:
    errors = []
    for sentence, must, must_not in LEXICON_TESTS:
        found = themes_of(sentence)
        if not must <= found or found & must_not:
            errors.append(f"  « {sentence} » → {sorted(found)} (attendu : {sorted(must)}, interdit : {sorted(must_not)})")
    if errors:
        raise SystemExit("Le lexique des thèmes classe mal des phrases témoins :\n" + "\n".join(errors))


# ─────────────────────────────────────────────────────────────────────────────
# Petits outils statistiques
# ─────────────────────────────────────────────────────────────────────────────
def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Fourchette à 95 % d'un pourcentage (méthode de Wilson, fiable même avec peu d'avis)."""
    if n == 0:
        return (math.nan, math.nan)
    p = k / n
    den = 1 + z**2 / n
    centre = (p + z**2 / (2 * n)) / den
    half = z * math.sqrt(p * (1 - p) / n + z**2 / (4 * n**2)) / den
    return (100 * max(0.0, centre - half), 100 * min(1.0, centre + half))


def r(x, nd: int = 2):
    """Arrondi tolérant aux valeurs manquantes (→ None dans le JSON)."""
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return None
    return round(float(x), nd)


def pct(mask) -> float:
    return float(mask.mean() * 100) if len(mask) else math.nan


def score_block(g: pd.DataFrame) -> dict:
    """Indicateurs de base pour un groupe d'avis."""
    n = len(g)
    neg = int((g["score"] <= 2).sum())
    lo, hi = wilson(neg, n)
    return {
        "n": n,
        "avg": r(g["score"].mean()),
        "pct_neg": r(100 * neg / n if n else math.nan, 1),
        "neg_lo": r(lo, 1), "neg_hi": r(hi, 1),
        "pct_pos": r(pct(g["score"] >= 4), 1),
    }


def to_json_safe(obj):
    if isinstance(obj, dict):
        return {str(k): to_json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [to_json_safe(v) for v in obj]
    if isinstance(obj, float) and math.isnan(obj):
        return None
    if hasattr(obj, "item"):          # types numpy
        return to_json_safe(obj.item())
    return obj


def reply_core(text: str) -> str:
    """Cœur d'une réponse d'éditeur, sans formule d'appel ni signature (pour repérer les copier-coller)."""
    t = normalize(text).split("^")[0]
    t = re.sub(r"^(?:hello|hi|bonjour|bonsoir|cher|chere|dear)[^,!.]{0,40}[,!.]", "", t)
    t = re.sub(r"[^a-z ]", " ", t)
    return " ".join(t.split()[:12])


def main() -> None:
    check_lexicon()

    # ─────────────────────────────────────────────────────────────────────────
    # 2. CHARGEMENT & NETTOYAGE
    # ─────────────────────────────────────────────────────────────────────────
    raw = pd.read_csv(ROOT / "data/all_playstore_reviews.csv")
    n_raw = len(raw)
    dup_ids = int(raw["reviewId"].duplicated().sum())
    df = raw.drop_duplicates("reviewId").dropna(subset=["content"]).copy()
    df["at"] = pd.to_datetime(df["at"], errors="coerce")
    df = df.dropna(subset=["at"])
    df["month"] = df["at"].dt.to_period("M").astype(str)
    df["category"] = df["app_name"].map(lambda a: "Banque" if a in BANKS else "Mobile Money")
    df["n_words"] = df["content"].map(lambda s: len(normalize(s).split()))
    df["is_short"] = df["n_words"] <= SHORT_REVIEW_WORDS
    df["has_reply"] = df["replyContent"].notna()
    df["sentiment"] = pd.cut(df["score"], [0, 2, 3, 5], labels=["Négatif", "Neutre", "Positif"])
    df["is_neg"] = df["score"] <= 2

    # ─────────────────────────────────────────────────────────────────────────
    # 3. THÈMES
    # ─────────────────────────────────────────────────────────────────────────
    found = df["content"].map(themes_of)
    for t in THEMES:
        df[t] = found.map(lambda s, t=t: t in s)
    df["n_themes"] = found.map(len)
    pain = [t for t in THEMES if t not in POSITIVE_THEMES]
    df["any_pain"] = df[pain].any(axis=1)

    out_cols = ["reviewId", "score", "content", "at", "replyContent", "appVersion", "userName",
                "thumbsUpCount", "app_id", "app_name", "month", "category", "n_words", "is_short",
                "has_reply", "sentiment", *THEMES, "n_themes"]
    df[out_cols].to_csv(ROOT / "data/reviews_clean.csv", index=False, encoding="utf-8-sig")

    neg = df[df["is_neg"]]
    end = df["at"].max()
    start = df["at"].min()

    # ─────────────────────────────────────────────────────────────────────────
    # 4. INDICATEURS
    # ─────────────────────────────────────────────────────────────────────────
    agg: dict = {}

    # 4.a Couverture : quelles périodes sont réellement comparables ?
    cov = df.groupby("app_name").agg(n=("reviewId", "size"), first=("at", "min"), last=("at", "max"))
    cov["capped"] = cov["n"] >= CAP_PER_APP
    # Pour une app tronquée, on n'a que ses 5 000 avis les plus récents : sa période couverte
    # commence à son 1er avis collecté. La « fenêtre commune » commence quand TOUTES les apps
    # tronquées sont couvertes — à l'intérieur, toutes les apps sont comparées sur la même période.
    window_start = cov.loc[cov["capped"], "first"].max() if cov["capped"].any() else start
    in_window = df["at"] >= window_start
    trend_mid = end - pd.DateOffset(months=TREND_MONTHS)
    trend_start = end - pd.DateOffset(months=2 * TREND_MONTHS)

    # 4.b Réponses des éditeurs : part de réponses « modèles » (même texte ≥ 3 fois)
    rep = df[df["has_reply"]].copy()
    rep["core"] = rep["replyContent"].map(reply_core)
    rep["templated"] = rep.groupby(["app_name", "core"])["core"].transform("size") >= 3
    templated_by_app = rep.groupby("app_name")["templated"].agg(["size", "mean"])

    # 4.c KPI globaux
    m_global = df["score"].mean()
    agg["kpis"] = {
        "total_reviews": len(df),
        "n_apps": int(df["app_name"].nunique()),
        "avg_score": r(m_global),
        "pct_negative": r(pct(df["is_neg"]), 1),
        "pct_positive": r(pct(df["score"] >= 4), 1),
        "reply_rate": r(pct(df["has_reply"]), 1),
        "reply_rate_neg": r(pct(neg["has_reply"]), 1),
        "templated_reply_share": r(100 * rep["templated"].mean(), 1),
        "pct_short": r(pct(df["is_short"]), 1),
        "neg_with_theme": r(pct(neg["any_pain"]), 1),
        "neg_with_theme_long": r(pct(neg.loc[~neg["is_short"], "any_pain"]), 1),
        "period": f"{start.date()} → {end.date()}",
        "period_start": str(start.date()), "period_end": str(end.date()),
    }
    agg["data_quality"] = {
        "raw_rows": n_raw,
        "duplicate_ids_removed": dup_ids,
        "empty_or_undated_removed": int(n_raw - dup_ids - len(df)),
        "pct_without_version": r(pct(df["appVersion"].isna()), 1),
        "capped_apps": sorted(cov.index[cov["capped"]].tolist()),
    }
    agg["params"] = {
        "cap_per_app": CAP_PER_APP, "min_reviews_ranking": MIN_REVIEWS_RANKING,
        "prior_weight": PRIOR_WEIGHT, "min_reviews_window": MIN_REVIEWS_WINDOW,
        "trend_months": TREND_MONTHS, "min_version_reviews": MIN_VERSION_REVIEWS,
        "short_review_words": SHORT_REVIEW_WORDS, "min_neg_for_matrix": MIN_NEG_FOR_MATRIX,
    }
    agg["windows"] = {
        "common_start": str(window_start.date()), "common_end": str(end.date()),
        "trend_prev": f"{trend_start.date()} → {trend_mid.date()}",
        "trend_recent": f"{trend_mid.date()} → {end.date()}",
    }

    # 4.d Par application
    rows = []
    for app, g in df.groupby("app_name"):
        c = cov.loc[app]
        b = score_block(g)
        gn = g[g["is_neg"]]
        # note ajustée (moyenne « bayésienne ») : protège contre les apps à 5 avis notées 5/5
        adj = (g["score"].sum() + PRIOR_WEIGHT * m_global) / (len(g) + PRIOR_WEIGHT)
        w = g[g["at"] >= window_start]
        prev = g[(g["at"] > trend_start) & (g["at"] <= trend_mid)]
        recent = g[g["at"] > trend_mid]
        prev_complete = (not c["capped"]) or c["first"] <= trend_start
        trend_ok = prev_complete and len(prev) >= MIN_REVIEWS_WINDOW and len(recent) >= MIN_REVIEWS_WINDOW
        top_pain = None
        if len(gn) >= 20:
            shares = gn[pain].mean().sort_values(ascending=False)
            top_pain = {"theme": shares.index[0], "pct": r(100 * shares.iloc[0], 1)}
        tpl = templated_by_app["mean"].get(app) if templated_by_app["size"].get(app, 0) >= 20 else None
        rows.append({
            "app_name": app, "cat": g["category"].iloc[0], "reviews": b["n"],
            "avg": b["avg"], "adj": r(adj), "pct_neg": b["pct_neg"],
            "neg_lo": b["neg_lo"], "neg_hi": b["neg_hi"], "pct_pos": b["pct_pos"],
            "reply": r(pct(g["has_reply"]), 1), "reply_neg": r(pct(gn["has_reply"]), 1) if len(gn) else None,
            "templated": r(100 * tpl, 1) if tpl is not None else None,
            "first": str(c["first"].date()), "last": str(c["last"].date()), "capped": bool(c["capped"]),
            "window_n": len(w), "window_avg": r(w["score"].mean()) if len(w) >= MIN_REVIEWS_WINDOW else None,
            "window_pct_neg": r(pct(w["is_neg"]), 1) if len(w) >= MIN_REVIEWS_WINDOW else None,
            "prev_avg": r(prev["score"].mean()) if trend_ok else None,
            "recent_avg": r(recent["score"].mean()) if trend_ok else None,
            "trend": r(recent["score"].mean() - prev["score"].mean()) if trend_ok else None,
            "n_neg": len(gn), "top_pain": top_pain,
            "ranked": b["n"] >= MIN_REVIEWS_RANKING,
        })
    agg["by_app"] = sorted(rows, key=lambda x: -x["reviews"])

    # 4.e Par catégorie : moyenne pondérée par les avis, moyenne simple des apps, fenêtre commune
    cats = []
    for cat, g in df.groupby("category"):
        apps = [a for a in rows if a["cat"] == cat and a["ranked"]]
        w = g[g["at"] >= window_start]
        cats.append({
            "category": cat, **score_block(g),
            "n_apps": int(g["app_name"].nunique()),
            "avg_of_apps": r(sum(a["avg"] for a in apps) / len(apps)) if apps else None,
            "window": score_block(w),
        })
    agg["by_category"] = cats

    # 4.f Distribution des notes (global et par catégorie, en %)
    agg["score_dist"] = {int(k): int(v) for k, v in df["score"].value_counts().sort_index().items()}
    agg["score_dist_by_category"] = {
        cat: {int(k): r(100 * v, 1) for k, v in g["score"].value_counts(normalize=True).sort_index().items()}
        for cat, g in df.groupby("category")
    }

    # 4.g Évolution mensuelle (global + par catégorie) et des principales apps
    mo = df[df["at"] >= MONTHLY_SINCE]
    monthly = mo.groupby("month").agg(n=("score", "size"), avg=("score", "mean"))
    by_cat = mo.groupby(["month", "category"])["score"].agg(["size", "mean"]).unstack()
    agg["monthly"] = [
        {"month": m, "n": int(row["n"]), "avg": r(row["avg"]),
         "n_bk": int(by_cat[("size", "Banque")].get(m, 0) or 0) if ("size", "Banque") in by_cat else 0,
         "n_mm": int(by_cat[("size", "Mobile Money")].get(m, 0) or 0) if ("size", "Mobile Money") in by_cat else 0,
         "avg_bk": r(by_cat[("mean", "Banque")].get(m)) if ("mean", "Banque") in by_cat else None,
         "avg_mm": r(by_cat[("mean", "Mobile Money")].get(m)) if ("mean", "Mobile Money") in by_cat else None}
        for m, row in monthly.iterrows()
    ]
    agg["sample_entries"] = [
        {"app": a, "first": str(cov.loc[a, "first"].date()), "month": str(cov.loc[a, "first"].to_period("M"))}
        for a in cov.index[cov["capped"]] if cov.loc[a, "first"] >= pd.Timestamp(MONTHLY_SINCE)
    ]
    top6 = [a["app_name"] for a in agg["by_app"][:6]]
    ma = (df[(df["at"] >= APP_TRENDS_SINCE) & df["app_name"].isin(top6)]
          .groupby(["month", "app_name"])["score"].agg(["size", "mean"]))
    ma = ma[ma["size"] >= 10]["mean"].round(2).unstack().reset_index()
    agg["monthly_by_app"] = json.loads(ma.to_json(orient="records"))

    # 4.h Thèmes : fréquence, gravité, poids dans les plaintes, votes « utile »
    themes = []
    for t in THEMES:
        s = df[t]
        sn = neg[t]
        themes.append({
            "theme": t, "positive": t in POSITIVE_THEMES,
            "n": int(s.sum()),
            "avg": r(df.loc[s, "score"].mean()),
            "pct_neg": r(pct(df.loc[s, "is_neg"]), 1),
            "share_of_neg": r(pct(sn), 1),                                   # % des avis négatifs qui citent le thème
            "share_of_neg_bk": r(pct(neg.loc[neg["category"] == "Banque", t]), 1),
            "share_of_neg_mm": r(pct(neg.loc[neg["category"] == "Mobile Money", t]), 1),
            "thumbs_neg": int(neg.loc[sn, "thumbsUpCount"].sum()),            # nb de « utile » sur ces plaintes
        })
    themes.sort(key=lambda x: (x["positive"], -x["share_of_neg"]))
    agg["themes"] = themes

    # 4.i Matrice app × thème : % des avis négatifs de chaque app qui citent chaque thème
    matrix = []
    for app, g in neg.groupby("app_name"):
        if len(g) >= MIN_NEG_FOR_MATRIX:
            matrix.append({"app": app, "n_neg": len(g), "cat": g["category"].iloc[0],
                           "values": {t: r(100 * g[t].mean(), 1) for t in pain}})
    agg["theme_matrix"] = sorted(matrix, key=lambda x: -x["n_neg"])

    # 4.j Versions : quelles mises à jour ont fait monter ou chuter la satisfaction ?
    versions = {}
    for app, g in df.dropna(subset=["appVersion"]).groupby("app_name"):
        if len(g) < 300:
            continue
        v = (g.groupby("appVersion")
             .agg(n=("score", "size"), avg=("score", "mean"), neg=("is_neg", "mean"),
                  n_neg=("is_neg", "sum"), n_pos=("score", lambda x: int((x >= 4).sum())), first=("at", "min"))
             .query("n >= @MIN_VERSION_REVIEWS").sort_values("first"))
        if len(v) >= 3:
            versions[app] = [{"version": str(k), "first": str(x["first"].date()), "n": int(x["n"]),
                              "avg": r(x["avg"]), "pct_neg": r(100 * x["neg"], 1),
                              "n_neg": int(x["n_neg"]), "n_pos": int(x["n_pos"])} for k, x in v.iterrows()]
    agg["versions"] = versions

    # 4.k Réponses des éditeurs
    agg["replies"] = {
        "by_score": {int(k): r(100 * v, 1) for k, v in df.groupby("score")["has_reply"].mean().items()},
    }

    # 4.l Verbatims : les plaintes les plus « approuvées » (votes utile) par thème, sans nom d'auteur.
    #     On privilégie les avis centrés sur 1 ou 2 thèmes (plus représentatifs du thème illustré).
    used: set[str] = set()
    verb = {}
    pool = df[df["n_words"] >= 12].assign(focused=lambda d: d["n_themes"] <= 2)
    pool = pool.sort_values(["focused", "thumbsUpCount", "at"], ascending=False)
    for t in THEMES:
        sel = pool[pool[t] & (pool["score"] >= 4 if t in POSITIVE_THEMES else pool["is_neg"])]
        picks = []
        for _, x in sel.iterrows():
            if x["reviewId"] in used:
                continue
            used.add(x["reviewId"])
            txt = re.sub(r"\s+", " ", str(x["content"])).strip()
            picks.append({"app": x["app_name"], "score": int(x["score"]), "date": str(x["at"].date()),
                          "thumbs": int(x["thumbsUpCount"]),
                          "text": txt if len(txt) <= 320 else txt[:317].rsplit(" ", 1)[0] + "…"})
            if len(picks) == 3:
                break
        verb[t] = picks
    agg["verbatims"] = verb

    # ─────────────────────────────────────────────────────────────────────────
    # 5. EXPORT
    # ─────────────────────────────────────────────────────────────────────────
    agg = to_json_safe(agg)
    (ROOT / "analysis/aggregates.json").write_text(json.dumps(agg, ensure_ascii=False, indent=1), encoding="utf-8")
    (ROOT / "docs/data.js").write_text(
        "// Fichier généré automatiquement par analysis/analyze_reviews.py — ne pas modifier à la main.\n"
        "window.D = " + json.dumps(agg, ensure_ascii=False) + ";\n", encoding="utf-8")

    k = agg["kpis"]
    print(f"✔ {k['total_reviews']:,} avis · {k['n_apps']} apps · note moyenne {k['avg_score']} · "
          f"{k['pct_negative']} % négatifs".replace(",", " "))
    print(f"✔ Fenêtre commune de comparaison : {agg['windows']['common_start']} → {agg['windows']['common_end']}")
    print("✔ Fichiers écrits : data/reviews_clean.csv · analysis/aggregates.json · docs/data.js")


if __name__ == "__main__":
    main()
