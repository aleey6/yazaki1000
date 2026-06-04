# YAZAKI · Extracteur de factures IAM

## Lancement
```bash
pip install -r requirements.txt
streamlit run app.py
```

## Utilisation
1. Onglet **Analyser la facture** → uploadez le PDF IAM
2. Le système détecte automatiquement l'usine via le N° Client
3. Chaque N° d'Appel est affecté à son département
4. Le budget restant est calculé par centre de coût

## Configuration
- Onglet **⚙️ Configuration** → gérez le mapping N° Client / Usine
- Modifiez les budgets, Cost Center IDs, et numéros par département
- Tout est persisté dans `config.json`
