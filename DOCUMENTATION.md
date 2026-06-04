# YAZAKI · Extracteur de Factures IAM — Documentation Complète

## Vue d'ensemble

Cette application est un **outil interne YAZAKI** développé avec **Streamlit** qui automatise l'extraction, l'analyse et le suivi budgétaire des factures télécom **IAM (Maroc Telecom)**. Elle permet de transformer un PDF de facture multi-pages en données structurées, d'affecter automatiquement chaque ligne téléphonique à son département, et de calculer le budget restant par centre de coût.

---

## Architecture de l'application

```
┌─────────────────────────────────────────────────────────────┐
│                    app.py (Interface Streamlit)              │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────┐  │
│  │ Onglet 1     │  │ Onglet 2     │  │ Onglet 3         │  │
│  │ Analyser     │  │ Configuration│  │ Historique        │  │
│  └──────┬───────┘  └──────┬───────┘  └────────┬─────────┘  │
└─────────┼──────────────────┼───────────────────┼────────────┘
          │                  │                   │
          ▼                  ▼                   ▼
┌──────────────────┐  ┌───────────┐     ┌──────────────┐
│ invoice_parser.py│  │config.json│     │ database.py  │
│ ocr_engine.py    │  │           │     │ (SQLite)     │
└──────────────────┘  └───────────┘     └──────────────┘
          │
          ▼
┌──────────────────┐
│ excel_export.py  │
│ invoice_utils.py │
│ budget_utils.py  │
└──────────────────┘
```

---

## Flux de traitement principal

### Étape 1 — Upload du PDF

L'utilisateur importe un ou plusieurs fichiers PDF de factures IAM via l'interface web.

### Étape 2 — Détection automatique (PDF natif ou scanné)

L'application vérifie si le PDF contient du texte extractible :
- **PDF natif** → extraction directe du texte avec `pdfplumber`
- **PDF scanné** → activation automatique de l'OCR via `EasyOCR` + `PyMuPDF`

### Étape 3 — Parsing de la facture

Le module `invoice_parser.py` parcourt chaque page du PDF et identifie :
- **Page globale** : résumé financier (HT, TVA, TTC, montant dû)
- **Pages contrat** : détail par ligne téléphonique (frais mensuels, frais ponctuels, total contrat)

Données extraites par facture :
| Champ | Description |
|-------|-------------|
| N° Facture | Identifiant unique de la facture |
| N° Client | Identifiant du client YAZAKI chez IAM |
| Date Facture | Date d'émission |
| Période facturée | Début → Fin |
| Contrats | Liste de tous les contrats (lignes téléphoniques) |
| Total | Somme de tous les TOTAL CONTRAT |

### Étape 4 — Identification automatique de l'usine

Le **N° Client** extrait de la facture est comparé au mapping configuré dans `config.json` :
```
N° Client "6.100149.00.00.100002" → Usine "MEKNES"
```

### Étape 5 — Affectation des lignes aux départements

Chaque **N° d'Appel** (numéro de téléphone) trouvé dans les contrats est comparé à la liste des numéros configurés par département. Exemple :
```
06 62 72 05 69 → Département IT (Usine MEKNES)
06 63 44 38 34 → Département Production (Usine MEKNES)
```

### Étape 6 — Calcul budgétaire

Pour chaque département, l'application calcule :
- **Budget alloué** (configuré dans config.json)
- **Dépenses** (somme des TOTAL CONTRAT des lignes du département)
- **Budget restant** = Budget - Dépenses
- **% d'utilisation** avec indicateurs visuels (🟢 OK / 🟡 Attention / 🟠 Critique / 🔴 Dépassement)

### Étape 7 — Sauvegarde et export

- **SQLite** : sauvegarde automatique de chaque facture analysée (avec contrats et lignes détaillées)
- **Excel** : export téléchargeable avec mise en forme YAZAKI (couleurs, bordures, totaux)

---

## Modules détaillés

### `app.py` — Interface principale

Point d'entrée Streamlit avec 3 onglets :

1. **Analyser la facture** : upload PDF, extraction, affichage des résultats avec ventilation budgétaire
2. **Configuration** : gestion du mapping N° Client → Usine, départements, budgets, numéros de téléphone
3. **Historique** : consultation et suppression des factures enregistrées

### `invoice_parser.py` — Moteur d'extraction PDF

- Utilise des **expressions régulières** pour identifier les champs structurés dans le texte
- Distingue les pages "globales" (résumé) des pages "contrat" (détail par ligne)
- Extrait les frais mensuels (avec dates) et ponctuels (sans dates)
- Calcule le total comme somme de tous les `TOTAL CONTRAT`

### `ocr_engine.py` — OCR pour PDF scannés

- Singleton utilisant **EasyOCR** (français + anglais)
- Convertit chaque page PDF en image PNG via PyMuPDF
- Retourne le texte reconnu pour le passer au parser
- Détecte automatiquement si un PDF est scanné (peu ou pas de texte extractible)

### `database.py` — Persistance SQLite

Schéma relationnel à 3 niveaux :
```
invoices (1 facture)
   └── contracts (N contrats/lignes)
         └── line_items (N frais mensuels/ponctuels)
```

Fonctionnalités :
- Sauvegarde avec dédoublication (clé unique : usine + département + projet + N° facture)
- Requêtes d'agrégation (total par usine/département/projet)
- Conservation du JSON brut complet pour traçabilité
- Suppression en cascade

### `excel_export.py` — Export Excel

- Génère un fichier `.xlsx` formaté avec les couleurs YAZAKI (rouge, noir, blanc)
- Mode **simple** (1 facture) et mode **batch** (plusieurs factures)
- Inclut métadonnées, en-têtes stylisés, alternance de couleurs, ligne de total

### `config.py` — Configuration globale

- Chemins (racine, data, fichier master)
- Palette de couleurs YAZAKI
- Fonctions utilitaires (formatage monétaire, nettoyage de noms de fichiers, normalisation de texte)

### `budget_utils.py` — Utilitaires budget

- Lecture de budgets depuis un fichier Excel externe
- Détection automatique de la ligne d'en-tête
- Matching normalisé (insensible aux accents, espaces, casse)

### `invoice_utils.py` — Utilitaires factures

- Conversion des contrats en DataFrame pandas
- Gestion du fichier master JSON (legacy)
- Chargement singleton de l'OCR engine

### `ui_components.py` — Composants UI

- CSS personnalisé avec les variables de couleur YAZAKI
- Cartes d'information stylisées
- Initialisation de l'état de session Streamlit

---

## Configuration (`config.json`)

Le fichier de configuration central contient :

```json
{
  "client_plant_mapping": {
    "<N° Client IAM>": "<Nom Usine>"
  },
  "plants": {
    "<Nom Usine>": {
      "departments": {
        "<Nom Département>": {
          "cost_center_id": "<ID Centre de Coût>",
          "budget": <montant en MAD>,
          "phone_numbers": ["06 XX XX XX XX", ...]
        }
      }
    }
  }
}
```

Tout est éditable directement depuis l'onglet **⚙️ Configuration** de l'interface.

---

## Technologies utilisées

| Technologie | Rôle |
|-------------|------|
| **Streamlit** | Interface web interactive |
| **pdfplumber** | Extraction de texte depuis PDF natifs |
| **PyMuPDF (fitz)** | Rendu de pages PDF en images pour OCR |
| **EasyOCR** | Reconnaissance optique de caractères |
| **pandas** | Manipulation de données tabulaires |
| **openpyxl** | Génération de fichiers Excel formatés |
| **SQLite** | Base de données locale pour l'historique |

---

## Lancement

```bash
pip install -r requirements.txt
streamlit run app.py
```

L'application s'ouvre dans le navigateur sur `http://localhost:8501`.

---

## Résumé du processus en une phrase

> L'application prend un PDF de facture IAM, en extrait automatiquement tous les contrats téléphoniques (même si le PDF est scanné), identifie l'usine et le département de chaque ligne, calcule le budget restant par centre de coût, et sauvegarde le tout en base de données avec possibilité d'export Excel.
