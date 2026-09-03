#!/usr/bin/env python3
"""
Convertit un export CSV de produits Shopify en fiches livres Jekyll
(_livres/*.md), en réutilisant directement les champs déjà renseignés dans
Shopify (éditeur, âge, autrice, série, fiche pédagogique, lien d'achat) —
rien à retaper à la main.

Ne dépend que de la bibliothèque standard Python (aucune installation requise).

CHAMPS SHOPIFY RECONNUS
------------------------
- Vendor                                            -> éditeur
- Tags "livreLora" / "LivreCaro" (un ou les deux)    -> autrice(s) du livre
- Tags "X ans" (sinon le métachamp Tranche d'âge)    -> âge
- Métachamp Série (product.metafields.custom.s_rie)  -> collection/série
- Métachamp Contenu pedago (...contenu_pedago)       -> lien PDF fiche pédagogique
- Métachamp Lien achat (...lien_achat)                -> lien vers le point de vente
- Les autres tags (hors "X ans", livreLora, LivreCaro)-> mots-clés

Les produits tagués "Animation" (ou anim1/anim2/anim3/animPresco) sont
ignorés : ce ne sont pas des livres, mais des offres d'animation déjà
couvertes par les pages animations.md / parcours-litteraire.md.

Un produit sans tag livreLora ni LivreCaro (mais qui ressemble à un livre)
est quand même importé, avec un avertissement — vérifie et assigne
l'autrice manuellement dans ce cas.

UTILISATION 
-----------
    python3 scripts/import_shopify.py chemin/vers/export.csv

Relance le script sans risque : les fichiers existants ne sont pas écrasés
par défaut (utilise --forcer pour les remplacer).
"""

import argparse
import csv
import os
import re
import sys
import urllib.request
from html.parser import HTMLParser

# Noms exacts des colonnes dans l'export Shopify (avec metachamps custom)
COL_CONTENU_PEDAGO = "Contenu pedago (product.metafields.custom.contenu_pedago)"
COL_LIEN_ACHAT = "Lien achat (product.metafields.custom.lien_achat)"
COL_SERIE = "Série (product.metafields.custom.s_rie)"
COL_TRANCHE_AGE = "Tranche d'âge (product.metafields.custom.tranches_d_ge)"

TAG_AUTEURE = {
    "livrelora": "lora",
    "livrecaro": "carolyn",
}


class TexteSimpleHTML(HTMLParser):
    """Convertit grossièrement le Body (HTML) de Shopify en texte lisible."""

    BLOC = {"p", "div", "li", "br", "h1", "h2", "h3", "h4"}

    def __init__(self):
        super().__init__()
        self.morceaux = []

    def handle_starttag(self, tag, attrs):
        if tag == "li":
            self.morceaux.append("\n- ")
        elif tag in self.BLOC:
            self.morceaux.append("\n")

    def handle_endtag(self, tag):
        if tag in self.BLOC:
            self.morceaux.append("\n")

    def handle_data(self, data):
        self.morceaux.append(data)

    def texte(self):
        brut = "".join(self.morceaux)
        brut = re.sub(r"[ \t]+", " ", brut)
        brut = re.sub(r"\n{3,}", "\n\n", brut)
        return brut.strip()


def html_vers_texte(html):
    if not html:
        return ""
    html = html.replace("\r\n", "\n").replace("\r", "\n")
    parseur = TexteSimpleHTML()
    parseur.feed(html)
    return parseur.texte()


def slugifier(texte):
    texte = texte.lower().strip()
    texte = re.sub(r"[àâä]", "a", texte)
    texte = re.sub(r"[éèêë]", "e", texte)
    texte = re.sub(r"[îï]", "i", texte)
    texte = re.sub(r"[ôö]", "o", texte)
    texte = re.sub(r"[ùûü]", "u", texte)
    texte = re.sub(r"[ç]", "c", texte)
    texte = re.sub(r"[^a-z0-9]+", "-", texte)
    return texte.strip("-")


def echapper_yaml(valeur):
    return valeur.replace('"', '\\"')


def analyser_tags(tags_brut):
    """Sépare les tags Shopify en (autrices, age, mots_cles, est_animation)."""
    tags = [t.strip() for t in tags_brut.split(",") if t.strip()]
    autrices = []
    age = ""
    mots_cles = []
    est_animation = False

    for tag in tags:
        cle = tag.lower()
        if cle.startswith("anim") or cle == "animation":
            est_animation = True
            continue
        if cle in TAG_AUTEURE:
            if TAG_AUTEURE[cle] not in autrices:
                autrices.append(TAG_AUTEURE[cle])
            continue
        if re.match(r"^\d+(-\d+)?\s*ans$", cle):
            age = age or tag
            continue
        mots_cles.append(tag)

    return autrices, age, mots_cles, est_animation


def regrouper_par_produit(chemin_csv):
    """Regroupe les lignes du CSV Shopify par Handle (= un produit)."""
    produits = {}
    ordre = []
    with open(chemin_csv, newline="", encoding="utf-8-sig") as f:
        lecteur = csv.DictReader(f)
        for ligne in lecteur:
            handle = ligne.get("Handle", "").strip()
            if not handle:
                continue
            if handle not in produits:
                produits[handle] = {
                    "titre": "",
                    "corps_html": "",
                    "images": [],
                    "vendor": "",
                    "tags": "",
                    "fiche_pedagogique": "",
                    "lien_achat": "",
                    "serie": "",
                    "tranche_age": "",
                }
                ordre.append(handle)

            p = produits[handle]
            if ligne.get("Title", "").strip():
                p["titre"] = ligne["Title"].strip()
            if ligne.get("Body (HTML)", "").strip() and not p["corps_html"]:
                p["corps_html"] = ligne["Body (HTML)"]
            if ligne.get("Vendor", "").strip():
                p["vendor"] = ligne["Vendor"].strip()
            if ligne.get("Tags", "").strip():
                p["tags"] = ligne["Tags"].strip()
            if ligne.get(COL_CONTENU_PEDAGO, "").strip():
                p["fiche_pedagogique"] = ligne[COL_CONTENU_PEDAGO].strip()
            if ligne.get(COL_LIEN_ACHAT, "").strip():
                p["lien_achat"] = ligne[COL_LIEN_ACHAT].strip()
            if ligne.get(COL_SERIE, "").strip():
                p["serie"] = ligne[COL_SERIE].strip()
            if ligne.get(COL_TRANCHE_AGE, "").strip():
                p["tranche_age"] = ligne[COL_TRANCHE_AGE].strip()

            src = ligne.get("Image Src", "").strip()
            pos = ligne.get("Image Position", "").strip()
            if src:
                p["images"].append((pos or "999", src))

    for handle in ordre:
        produits[handle]["images"].sort(key=lambda t: t[0])

    return [(h, produits[h]) for h in ordre]


def telecharger_image(url, destination):
    if os.path.exists(destination):
        return
    try:
        urllib.request.urlretrieve(url, destination)
        print(f"  image téléchargée -> {destination}")
    except Exception as e:
        print(f"  ATTENTION: échec du téléchargement de l'image ({e})."
              f" Ajoute-la manuellement dans {destination}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("csv", help="Chemin vers le CSV exporté de Shopify")
    ap.add_argument("--format", choices=["carre", "rectangle"], default="rectangle",
                     help="Format de couverture à assigner à tous les livres de ce CSV (défaut: rectangle)")
    ap.add_argument("--racine", default=".", help="Racine du projet Jekyll (défaut: dossier courant)")
    ap.add_argument("--forcer", action="store_true", help="Écrase les fiches livres existantes")
    ap.add_argument("--inclure-sans-autrice", action="store_true",
                     help="Importer aussi les produits sans tag livreLora/LivreCaro (par défaut ils sont ignorés)")
    args = ap.parse_args()

    dossier_livres = os.path.join(args.racine, "_livres")
    dossier_images = os.path.join(args.racine, "assets", "images", "livres")
    os.makedirs(dossier_livres, exist_ok=True)
    os.makedirs(dossier_images, exist_ok=True)

    produits = regrouper_par_produit(args.csv)
    if not produits:
        print("Aucun produit trouvé dans ce CSV.")
        sys.exit(1)

    importes = 0
    ignores_animation = 0
    ignores_sans_autrice = 0

    for handle, p in produits:
        titre = p["titre"] or handle
        autrices, age_tag, mots_cles, est_animation = analyser_tags(p["tags"])

        if est_animation:
            ignores_animation += 1
            continue

        if not autrices and not args.inclure_sans_autrice:
            print(f"- {titre}: ignoré (aucun tag livreLora/LivreCaro trouvé — "
                  f"relance avec --inclure-sans-autrice pour l'importer quand même)")
            ignores_sans_autrice += 1
            continue

        slug = slugifier(handle)
        chemin_fiche = os.path.join(dossier_livres, f"{slug}.md")

        if os.path.exists(chemin_fiche) and not args.forcer:
            print(f"- {titre}: fiche déjà existante, ignorée (--forcer pour écraser)")
            continue

        # Image principale
        chemin_image_relatif = f"/assets/images/livres/{slug}.jpg"
        if p["images"]:
            _, url_image = p["images"][0]
            ext = os.path.splitext(url_image.split("?")[0])[1] or ".jpg"
            chemin_image_relatif = f"/assets/images/livres/{slug}{ext}"
            chemin_image_absolu = os.path.join(dossier_images, f"{slug}{ext}")
            telecharger_image(url_image, chemin_image_absolu)
        else:
            print(f"  ATTENTION: aucune image trouvée pour {titre}, à ajouter manuellement.")

        resume = html_vers_texte(p["corps_html"]) or "Résumé du livre à ajouter."
        age = p["tranche_age"] or age_tag
        lien_achat = p["lien_achat"] or "https://lien-vers-le-point-de-vente.com"

        contenu = "---\n"
        contenu += f'title: "{echapper_yaml(titre)}"\n'
        if p["serie"]:
            contenu += f'serie: "{echapper_yaml(p["serie"])}"\n'
        if autrices:
            contenu += f"auteures: [{', '.join(autrices)}]\n"
        else:
            contenu += "auteures: []  # TODO: aucun tag livreLora/LivreCaro trouvé, assigne l'autrice\n"
        contenu += f"image: {chemin_image_relatif}\n"
        if args.format == "carre":
            contenu += "format: carre\n"
        contenu += f'lien_achat: "{lien_achat}"\n'
        if p["vendor"]:
            contenu += f'editeur: "{echapper_yaml(p["vendor"])}"\n'
        if age:
            contenu += f'age: "{echapper_yaml(age)}"\n'
        if p["fiche_pedagogique"]:
            contenu += f'fiche_pedagogique: "{p["fiche_pedagogique"]}"\n'
        if mots_cles:
            contenu += f"mots_cles: [{', '.join(echapper_yaml(m) for m in mots_cles)}]\n"
        contenu += "---\n"
        contenu += resume + "\n"

        with open(chemin_fiche, "w", encoding="utf-8") as f:
            f.write(contenu)

        print(f"- {titre}: fiche créée -> {chemin_fiche}")
        importes += 1

    print(f"\n{importes} livre(s) importé(s), {ignores_animation} produit(s) d'animation ignoré(s), "
          f"{ignores_sans_autrice} produit(s) sans autrice ignoré(s).")
    print("Vérifie chaque fiche dans _livres/ : résumé, âge, éditeur et lien d'achat.")


if __name__ == "__main__":
    main()