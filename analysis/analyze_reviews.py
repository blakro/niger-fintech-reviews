"""Analyse des avis Play Store (Mobile Money & Banques Niger).
Entrée : data/all_playstore_reviews.csv → Sorties : data/reviews_clean.csv, analysis/aggregates.json
Usage : python analysis/analyze_reviews.py
"""
import pandas as pd, json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
df = pd.read_csv(ROOT/'data/all_playstore_reviews.csv')
df['at'] = pd.to_datetime(df['at'], errors='coerce')
df = df.dropna(subset=['content']).copy()
df['month'] = df['at'].dt.to_period('M').astype(str)
low = df['content'].str.lower()

BANKS = {"Ecobank Mobile","MyBOA","BIA Niger Mobile","My KEAZ (Orabank)","BSIC NET",
         "Atlantique Mobile","BAGRINET","BIN MOBILE","BHN Mobile"}
df['category'] = df['app_name'].map(lambda a: 'Banque' if a in BANKS else 'Mobile Money')

THEMES = {
 'Connexion / OTP': r'connex|connect|login|se connecter|otp|code de v[ée]rif|mot de passe|password|authentif',
 'Bugs / Crashs': r'bug|crash|plante|ne marche pas|marche plus|fonctionne pas|erreur|error|bloqu',
 'Transactions': r'transfert|transaction|envoi|retrait|d[ée]p[ôo]t|paiement|payer|solde',
 'Frais / Tarifs': r'frais|co[ûu]t|cher|tarif|commission|gratuit',
 'Service client': r'service client|support|assistance|aucune aide|customer service|customer care',
 'Lenteur / Réseau': r'lent|lenteur|slow|r[ée]seau|network|charge pas|chargement|attente',
 'Mise à jour': r'mise [àa] jour|update|nouvelle version',
 'UX / Design': r'interface|design|facile|simple|pratique|intuitive|ergonomi',
 'Sécurité / Confiance': r's[ée]curi|confiance|arnaque|vol[ée]|fraude|compte bloqu',
}
for t, pat in THEMES.items():
    df[t] = low.str.contains(pat, regex=True, na=False)
df['sentiment'] = pd.cut(df['score'], [0,2,3,5], labels=['Négatif','Neutre','Positif'])
df.to_csv(ROOT/'data/reviews_clean.csv', index=False, encoding='utf-8-sig')

agg = {
 'kpis': {'total_reviews': int(len(df)), 'n_apps': int(df['app_name'].nunique()),
          'avg_score': round(float(df['score'].mean()),2),
          'pct_negative': round(float((df['score']<=2).mean()*100),1),
          'reply_rate': round(float(df['replyContent'].notna().mean()*100),1),
          'period': f"{df['at'].min().date()} → {df['at'].max().date()}"},
}
by_app = (df.groupby('app_name')
          .agg(reviews=('reviewId','count'), avg=('score','mean'),
               pct_neg=('score', lambda s:(s<=2).mean()*100),
               reply=('replyContent', lambda s:s.notna().mean()*100),
               cat=('category','first'))
          .round(2).sort_values('reviews',ascending=False).reset_index())
agg['by_app'] = by_app.to_dict('records')
agg['monthly'] = (df[df['at']>='2023-01-01'].groupby('month')
                  .agg(n=('reviewId','count'), avg=('score','mean')).round(2)
                  .reset_index().to_dict('records'))
agg['score_dist'] = {int(k):int(v) for k,v in df['score'].value_counts().sort_index().items()}
agg['by_category'] = (df.groupby('category').agg(n=('reviewId','count'), avg=('score','mean'))
                      .round(2).reset_index().to_dict('records'))
agg['themes'] = sorted(
    [{'theme':t,'n':int(df[t].sum()),
      'avg':round(float(df.loc[df[t],'score'].mean()),2),
      'pct_neg':round(float((df.loc[df[t],'score']<=2).mean()*100),1)} for t in THEMES],
    key=lambda r:-r['n'])
top6 = by_app.head(6)['app_name'].tolist()
agg['neg_themes_by_app'] = [
    {'app':a, **{t:int(df[(df['app_name']==a)&(df['score']<=2)][t].sum()) for t in THEMES}}
    for a in top6]
ma = (df[(df['at']>='2024-01-01')&df['app_name'].isin(top6)]
      .groupby(['month','app_name'])['score'].mean().round(2).unstack().reset_index())
agg['monthly_by_app'] = json.loads(ma.to_json(orient='records'))
json.dump(agg, open(ROOT/'analysis/aggregates.json','w'), ensure_ascii=False, indent=1)
print("OK →", ROOT/'analysis/aggregates.json')
