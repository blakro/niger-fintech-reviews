# 📱 Mobile Money & Banques Niger — Analyse des avis Google Play

Pipeline complet : **scraping → dataset → analyse → rapport business → dashboard HTML (GitHub Pages)**.

🔗 **Dashboard interactif** : `https://<votre-user>.github.io/<repo>/` (via GitHub Pages, dossier `docs/`)

## 🗂 Structure

```
├── notebooks/scrape_playstore_reviews.ipynb   # Scraping (google-play-scraper, checkpoints, retry)
├── data/
│   ├── all_playstore_reviews.csv              # Brut (32 587 lignes, 20 apps)
│   └── reviews_clean.csv                      # Nettoyé + thèmes + sentiment
├── analysis/
│   ├── analyze_reviews.py                     # Script reproductible
│   └── aggregates.json                        # Agrégats consommés par le dashboard
├── report/rapport_business.md                 # Rapport business (FR)
└── docs/index.html                            # Dashboard autonome (Chart.js, aucune dépendance serveur)
```

## 🚀 Reproduire

```bash
pip install pandas google-play-scraper
# 1. Scraping : exécuter le notebook (checkpoints/ permet de reprendre après crash)
# 2. Analyse :
python analysis/analyze_reviews.py
# 3. Ouvrir docs/index.html dans un navigateur
```

## 📊 Résultats clés

- **32 586 avis**, note moyenne **4,10/5**, 16,4 % d'avis négatifs
- Mobile Money (**4,51**) >> Banques (**3,62**)
- Top : My Nita 4,70 · Wave 4,64 — Flop : My KEAZ 2,38 · Ecobank 2,78
- Thèmes les plus toxiques : service client (75 % nég.), bugs/crashs (72 %), mises à jour (62 %), connexion/OTP (59 %)

## ⚠️ Limites

Avis auto-sélectionnés · apps multi-pays mélangent des avis hors Niger · plafond 5 000 avis/app · analyse volontairement limitée aux avis en français (`lang='fr'`), périmètre assumé du projet.

## Publication GitHub Pages

Settings → Pages → Source : *Deploy from a branch* → Branch `main`, dossier `/docs`.
