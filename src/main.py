import threading
import time
import traceback
from datetime import datetime

import flet as ft
import requests

# ==========================================
# CONFIGURATION
# ==========================================
FIREBASE_URL = "https://k-haime-suivi-48bc4-default-rtdb.firebaseio.com"
TIMEOUT = 10                 # secondes avant abandon d'une requête
SEUIL_EN_LIGNE_MIN = 15      # au-delà, un camion est considéré "Inactif"
ACTUALISATION_SEC = 30       # fréquence de l'actualisation automatique
PIN_PAR_DEFAUT = "1234"      # modifiable ensuite dans Réglages
CLE_PIN = "khaim_patron_pin"
CATEGORIES = ["Marchandise", "Citerne"]
FILTRES_STATUT = ["Tous", "En ligne", "Inactif", "Sans position"]
TITRES = ["Suivi des camions", "Gestion des camions", "Gestion des chauffeurs"]
CARACTERES_INTERDITS = set(".$#[]/")


class Couleurs:
    DARK_BLUE = "#0B1B36"
    YELLOW = "#FFC107"
    WHITE = "#FFFFFF"
    GREEN = "#2E9D5B"
    RED = "#D64545"
    ORANGE = "#F28C28"
    TEXT_GRAY = "#6C757D"
    BG_GRAY = "#F4F6FA"
    LIGHT_BLUE = "#E0E7FF"
    ALERTE_BG = "#FDECEA"


# ==========================================
# FIREBASE
# ==========================================
def _url(chemin):
    return f"{FIREBASE_URL}/{chemin}.json"


def fb_get(chemin):
    """Retourne les données ({} si vide) ou None en cas d'erreur de connexion."""
    try:
        r = requests.get(_url(chemin), timeout=TIMEOUT)
        if r.status_code == 200:
            return r.json() or {}
    except (requests.RequestException, ValueError):
        pass
    return None


def fb_put(chemin, donnees):
    try:
        return requests.put(_url(chemin), json=donnees, timeout=TIMEOUT).status_code == 200
    except requests.RequestException:
        return False


def fb_patch(chemin, donnees):
    """Met à jour seulement les champs donnés (conserve les autres champs)."""
    try:
        return requests.patch(_url(chemin), json=donnees, timeout=TIMEOUT).status_code == 200
    except requests.RequestException:
        return False


def fb_delete(chemin):
    try:
        return requests.delete(_url(chemin), timeout=TIMEOUT).status_code == 200
    except requests.RequestException:
        return False


# ==========================================
# OUTILS
# ==========================================
FORMATS_HEURE = [
    "%Y-%m-%d %H:%M:%S", "%d/%m/%Y %H:%M:%S", "%Y-%m-%d %H:%M",
    "%d/%m/%Y %H:%M", "%Y-%m-%dT%H:%M:%S",
]


def age_minutes(heure):
    """Minutes écoulées depuis 'heure', ou None si le format est inconnu."""
    if not heure:
        return None
    for fmt in FORMATS_HEURE:
        try:
            moment = datetime.strptime(str(heure).strip(), fmt)
            return max(0.0, (datetime.now() - moment).total_seconds() / 60)
        except ValueError:
            continue
    return None


def texte_age(minutes):
    if minutes is None:
        return ""
    if minutes < 1:
        return "à l'instant"
    if minutes < 60:
        return f"il y a {int(minutes)} min"
    if minutes < 1440:
        return f"il y a {int(minutes // 60)} h"
    return f"il y a {int(minutes // 1440)} j"


def lire_coordonnees(pos):
    try:
        return float(pos.get("latitude")), float(pos.get("longitude"))
    except (TypeError, ValueError, AttributeError):
        return None, None


def statut_camion(pos):
    """Calcule l'état d'un camion d'après sa dernière position."""
    pos = pos if isinstance(pos, dict) else {}
    lat, lng = lire_coordonnees(pos)
    if lat is None:
        return {"code": "Sans position", "couleur": Couleurs.TEXT_GRAY, "lat": None, "lng": None, "age": None, "heure": ""}
    age = age_minutes(pos.get("heure"))
    inactif = age is not None and age > SEUIL_EN_LIGNE_MIN
    return {
        "code": "Inactif" if inactif else "En ligne",
        "couleur": Couleurs.ORANGE if inactif else Couleurs.GREEN,
        "lat": lat, "lng": lng, "age": age, "heure": str(pos.get("heure", "")),
    }


def cle_valide(cle):
    return bool(cle) and not (set(cle) & CARACTERES_INTERDITS)


def texte(valeur, defaut=""):
    return str(valeur) if valeur not in (None, "") else defaut


# ==========================================
# APPLICATION
# ==========================================
def main_app(page: ft.Page):
    page.title = "K-HAIM Patron"
    page.theme_mode = ft.ThemeMode.LIGHT
    page.bgcolor = Couleurs.DARK_BLUE
    page.padding = 0

    etat = {
        "onglet": 0, "actif": False, "auto": True,
        "recherche_suivi": "", "filtre_statut": "Tous",
        "recherche_camions": "", "recherche_chauffeurs": "",
    }
    ui = {"corps": None, "sous_titre": None, "maj_suivi": None}

    def ic(nom):
        """Icône par son nom, avec une icône de secours si le nom n'existe pas."""
        return getattr(ft.Icons, nom, ft.Icons.CIRCLE)

    # ---------- composants communs ----------
    def notifier(message, couleur=Couleurs.GREEN):
        page.open(ft.SnackBar(ft.Text(message), bgcolor=couleur))
        page.update()

    def carte(contenu, **kw):
        return ft.Container(
            content=contenu,
            bgcolor=Couleurs.WHITE,
            border_radius=12,
            padding=14,
            shadow=ft.BoxShadow(blur_radius=6, color=ft.Colors.with_opacity(0.06, "black")),
            **kw,
        )

    def pastille(texte_, couleur):
        return ft.Container(
            content=ft.Text(texte_, size=10, color=Couleurs.WHITE, weight=ft.FontWeight.BOLD),
            bgcolor=couleur,
            padding=ft.padding.symmetric(horizontal=8, vertical=4),
            border_radius=6,
        )

    def stat_carte(libelle, valeur, couleur, texte_sombre=False):
        c = Couleurs.DARK_BLUE if texte_sombre else Couleurs.WHITE
        return ft.Container(
            expand=True, bgcolor=couleur, border_radius=10, padding=12,
            content=ft.Column(
                [
                    ft.Text(str(valeur), size=22, weight=ft.FontWeight.BOLD, color=c),
                    ft.Text(libelle, size=11, color=c),
                ],
                horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=2,
            ),
        )

    def titre_section(texte_):
        return ft.Text(texte_, size=15, weight=ft.FontWeight.BOLD, color=Couleurs.DARK_BLUE)

    def bouton(texte_, icone, couleur, action, texte_sombre=False, **kw):
        return ft.ElevatedButton(
            texte_, icon=icone, on_click=action,
            bgcolor=couleur,
            color=Couleurs.DARK_BLUE if texte_sombre else Couleurs.WHITE,
            height=44,
            style=ft.ButtonStyle(
                shape=ft.RoundedRectangleBorder(radius=10),
                text_style=ft.TextStyle(weight=ft.FontWeight.BOLD),
            ),
            **kw,
        )

    def confirmer(titre, message, action, libelle="Confirmer", couleur=Couleurs.RED):
        def oui(e):
            page.close(dlg)
            action()

        dlg = ft.AlertDialog(
            modal=True,
            title=ft.Text(titre),
            content=ft.Text(message),
            actions=[
                ft.TextButton("Annuler", on_click=lambda e: page.close(dlg)),
                ft.ElevatedButton(libelle, bgcolor=couleur, color=Couleurs.WHITE, on_click=oui),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        page.open(dlg)

    def banniere_erreur():
        return ft.Container(
            bgcolor=Couleurs.ALERTE_BG, border_radius=10, padding=12,
            content=ft.Column(
                [
                    ft.Text(
                        "Connexion impossible. Vérifiez votre internet puis réessayez.",
                        size=12, color=Couleurs.RED, weight=ft.FontWeight.BOLD,
                    ),
                    ft.TextButton("Réessayer", icon=ic("REFRESH"), on_click=lambda e: afficher_onglet()),
                ],
                spacing=4,
            ),
        )

    def appeler(telephone):
        if telephone:
            page.launch_url(f"tel:{telephone}")

    def ouvrir_carte(lat, lng):
        page.launch_url(f"https://www.google.com/maps?q={lat},{lng}")

    # ==========================================
    # ONGLET 1 : SUIVI
    # ==========================================
    def construire_suivi():
        corps = ui["corps"]
        zone = ft.Column(spacing=10)
        txt_maj = ft.Text("", size=11, color=Couleurs.TEXT_GRAY)
        donnees = {"camions": {}, "positions": {}, "erreur": False, "maj": ""}

        def charger():
            camions = fb_get("camions")
            positions = fb_get("positions")
            if camions is None or positions is None:
                donnees["erreur"] = True
            else:
                donnees.update(camions=camions, positions=positions, erreur=False)
            donnees["maj"] = datetime.now().strftime("%H:%M:%S")

        def carte_camion(cid, info, statut):
            categorie = texte(info.get("categorie"), "Marchandise")
            citerne = categorie == "Citerne"
            chauffeur = texte(info.get("chauffeur_nom"))
            tel = texte(info.get("chauffeur_tel"))

            if statut["lat"] is not None:
                detail_pos = f"{statut['lat']:.5f}, {statut['lng']:.5f}"
                age = texte_age(statut["age"])
                detail_heure = f"{statut['heure']} ({age})" if age else statut["heure"] or "Heure inconnue"
            else:
                detail_pos = "Position inconnue"
                detail_heure = "Aucune position reçue"

            lignes_boutons = [
                bouton(
                    "Voir sur la carte", ic("MAP"), Couleurs.YELLOW,
                    lambda e, la=statut["lat"], lo=statut["lng"]: ouvrir_carte(la, lo),
                    texte_sombre=True, expand=True, disabled=statut["lat"] is None,
                )
            ]
            if tel:
                lignes_boutons.append(
                    bouton("Appeler", ic("PHONE"), Couleurs.DARK_BLUE, lambda e, t=tel: appeler(t), expand=True)
                )

            return carte(ft.Column(
                [
                    ft.Row([
                        ft.Container(
                            content=ft.Icon(ic("LOCAL_GAS_STATION") if citerne else ic("LOCAL_SHIPPING"), color=Couleurs.WHITE, size=22),
                            bgcolor=Couleurs.ORANGE if citerne else Couleurs.DARK_BLUE,
                            width=44, height=44, border_radius=22, alignment=ft.alignment.center,
                        ),
                        ft.Column(
                            [
                                ft.Text(cid, weight=ft.FontWeight.BOLD, color=Couleurs.DARK_BLUE, size=15),
                                ft.Text(f"{texte(info.get('immatriculation'), 'Immatriculation inconnue')} • {categorie}", size=11, color=Couleurs.TEXT_GRAY),
                                ft.Text(
                                    f"Chauffeur : {chauffeur}" if chauffeur else "Chauffeur : non assigné",
                                    size=12, color=Couleurs.DARK_BLUE if chauffeur else Couleurs.RED,
                                ),
                            ],
                            spacing=2, expand=True,
                        ),
                        pastille(statut["code"], statut["couleur"]),
                    ]),
                    ft.Row([ft.Icon(ic("LOCATION_ON"), color=Couleurs.YELLOW, size=16), ft.Text(detail_pos, size=12, color=Couleurs.TEXT_GRAY)], spacing=6),
                    ft.Row([ft.Icon(ic("ACCESS_TIME"), color=Couleurs.TEXT_GRAY, size=16), ft.Text(detail_heure, size=12, color=Couleurs.TEXT_GRAY)], spacing=6),
                    ft.Row(lignes_boutons, spacing=10),
                ],
                spacing=8,
            ))

        def rendre():
            camions = donnees["camions"]
            positions = donnees["positions"]
            elements = []
            for cid, info in camions.items():
                if isinstance(info, dict):
                    elements.append((cid, info, statut_camion(positions.get(cid))))

            n_ligne = sum(1 for _, _, s in elements if s["code"] == "En ligne")
            n_inactif = sum(1 for _, _, s in elements if s["code"] == "Inactif")
            n_sans = sum(1 for _, _, s in elements if s["code"] == "Sans position")

            requete = etat["recherche_suivi"].lower()
            filtre = etat["filtre_statut"]
            visibles = []
            for cid, info, s in sorted(elements, key=lambda x: (x[2]["code"] != "En ligne", x[0])):
                if filtre != "Tous" and s["code"] != filtre:
                    continue
                recherche = f"{cid} {info.get('immatriculation', '')} {info.get('chauffeur_nom', '')}".lower()
                if requete and requete not in recherche:
                    continue
                visibles.append(carte_camion(cid, info, s))

            controles = []
            if donnees["erreur"]:
                controles.append(banniere_erreur())
            controles.append(ft.Row([
                stat_carte("Camions", len(elements), Couleurs.DARK_BLUE),
                stat_carte("En ligne", n_ligne, Couleurs.GREEN),
                stat_carte("Inactifs / sans signal", n_inactif + n_sans, Couleurs.TEXT_GRAY),
            ], spacing=8))
            if visibles:
                controles.extend(visibles)
            elif not elements and not donnees["erreur"]:
                controles.append(ft.Text("Aucun camion enregistré. Ajoutez-en dans l'onglet Camions.", color=Couleurs.TEXT_GRAY))
            elif elements:
                controles.append(ft.Text("Aucun camion ne correspond à la recherche.", color=Couleurs.TEXT_GRAY))
            zone.controls = controles
            txt_maj.value = f"Dernière actualisation : {donnees['maj']}"
            page.update()

        def actualiser(e=None):
            charger()
            rendre()

        def sur_recherche(e):
            etat["recherche_suivi"] = (e.control.value or "").strip()
            rendre()

        def sur_filtre(e):
            etat["filtre_statut"] = e.control.value
            rendre()

        def sur_auto(e):
            etat["auto"] = bool(e.control.value)

        corps.controls.extend([
            ft.TextField(
                label="Rechercher (camion, plaque, chauffeur)", prefix_icon=ic("SEARCH"),
                border_radius=10, bgcolor=Couleurs.WHITE, on_change=sur_recherche,
                value=etat["recherche_suivi"],
            ),
            ft.Dropdown(
                label="Statut", value=etat["filtre_statut"],
                options=[ft.dropdown.Option(f) for f in FILTRES_STATUT],
                border_radius=10, bgcolor=Couleurs.WHITE, on_change=sur_filtre,
            ),
            ft.Row(
                [
                    ft.Switch(label="Actualisation auto", value=etat["auto"], on_change=sur_auto, active_color=Couleurs.GREEN),
                    ft.IconButton(ic("REFRESH"), icon_color=Couleurs.DARK_BLUE, tooltip="Actualiser", on_click=actualiser),
                ],
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            ),
            txt_maj,
            zone,
        ])
        ui["maj_suivi"] = actualiser
        actualiser()

    # ==========================================
    # ONGLET 2 : CAMIONS
    # ==========================================
    def ouvrir_formulaire_camion(camion_id=None, info=None):
        modification = camion_id is not None
        info = info or {}
        f_id = ft.TextField(
            label="Identifiant (ex : K-HAIM-01)", value=camion_id or "",
            disabled=modification, capitalization=ft.TextCapitalization.CHARACTERS,
        )
        f_immat = ft.TextField(
            label="Immatriculation (ex : AC 345 609 DF)", value=texte(info.get("immatriculation")),
            capitalization=ft.TextCapitalization.CHARACTERS,
        )
        f_cat = ft.Dropdown(
            label="Catégorie", value=texte(info.get("categorie"), "Marchandise"),
            options=[ft.dropdown.Option(c) for c in CATEGORIES],
        )
        f_capacite = ft.TextField(label="Capacité (ex : 20 tonnes)", value=texte(info.get("capacite")))

        def enregistrer(e):
            cle = (f_id.value or "").strip().replace(" ", "_")
            immat = (f_immat.value or "").strip().upper()
            if not cle or not immat or not f_cat.value:
                notifier("Identifiant, immatriculation et catégorie sont obligatoires.", Couleurs.RED)
                return
            if not modification and not cle_valide(cle):
                notifier("L'identifiant ne doit pas contenir . $ # [ ] /", Couleurs.RED)
                return
            champs = {
                "immatriculation": immat,
                "categorie": f_cat.value,
                "capacite": (f_capacite.value or "").strip(),
            }
            if modification:
                ok = fb_patch(f"camions/{cle}", champs)
            else:
                existant = fb_get(f"camions/{cle}")
                if existant is None:
                    notifier("Connexion impossible.", Couleurs.RED)
                    return
                if existant:
                    notifier("Cet identifiant existe déjà.", Couleurs.RED)
                    return
                ok = fb_put(f"camions/{cle}", champs)
            if not ok:
                notifier("Échec de l'enregistrement. Vérifiez la connexion.", Couleurs.RED)
                return
            page.close(dlg)
            afficher_onglet()
            notifier("Camion enregistré")

        dlg = ft.AlertDialog(
            modal=True,
            title=ft.Text("Modifier le camion" if modification else "Nouveau camion"),
            content=ft.Column([f_id, f_immat, f_cat, f_capacite], tight=True, scroll=ft.ScrollMode.AUTO),
            actions=[
                ft.TextButton("Annuler", on_click=lambda e: page.close(dlg)),
                ft.ElevatedButton("Enregistrer", bgcolor=Couleurs.YELLOW, color=Couleurs.DARK_BLUE, on_click=enregistrer),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        page.open(dlg)

    def ouvrir_assignation(camion_id, info, camions):
        chauffeurs = fb_get("chauffeurs")
        if chauffeurs is None:
            notifier("Connexion impossible.", Couleurs.RED)
            return
        liste = sorted(
            [c for c in chauffeurs.values() if isinstance(c, dict) and c.get("nom")],
            key=lambda c: c["nom"].lower(),
        )
        if not liste:
            notifier("Aucun chauffeur. Ajoutez-en d'abord dans l'onglet Chauffeurs.", Couleurs.RED)
            return

        AUCUN = "__aucun__"
        dd = ft.Dropdown(
            label="Chauffeur",
            value=info.get("chauffeur_nom") or AUCUN,
            options=[ft.dropdown.Option(key=AUCUN, text="— Aucun (désassigner) —")] + [
                ft.dropdown.Option(key=c["nom"], text=f"{c['nom']} ({texte(c.get('telephone'), 'sans numéro')})")
                for c in liste
            ],
        )

        def enregistrer(e):
            if dd.value == AUCUN:
                champs = {"chauffeur_nom": "", "chauffeur_tel": ""}
            else:
                choisi = next((c for c in liste if c["nom"] == dd.value), None)
                if not choisi:
                    notifier("Sélectionnez un chauffeur.", Couleurs.RED)
                    return
                champs = {"chauffeur_nom": choisi["nom"], "chauffeur_tel": texte(choisi.get("telephone"))}
                # un chauffeur n'est assigné qu'à un seul camion à la fois
                for autre_id, autre in camions.items():
                    if autre_id != camion_id and isinstance(autre, dict) and autre.get("chauffeur_nom") == choisi["nom"]:
                        fb_patch(f"camions/{autre_id}", {"chauffeur_nom": "", "chauffeur_tel": ""})
            if not fb_patch(f"camions/{camion_id}", champs):
                notifier("Échec de l'enregistrement. Vérifiez la connexion.", Couleurs.RED)
                return
            page.close(dlg)
            afficher_onglet()
            notifier("Assignation enregistrée")

        dlg = ft.AlertDialog(
            modal=True,
            title=ft.Text(f"Assigner • {camion_id}"),
            content=ft.Column(
                [
                    ft.Text(f"Immatriculation : {texte(info.get('immatriculation'), 'N/A')}", size=12, color=Couleurs.TEXT_GRAY),
                    dd,
                    ft.Text("Un chauffeur ne peut être assigné qu'à un seul camion à la fois.", size=11, color=Couleurs.TEXT_GRAY),
                ],
                tight=True, spacing=10,
            ),
            actions=[
                ft.TextButton("Annuler", on_click=lambda e: page.close(dlg)),
                ft.ElevatedButton("Assigner", bgcolor=Couleurs.YELLOW, color=Couleurs.DARK_BLUE, on_click=enregistrer),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        page.open(dlg)

    def supprimer_camion(camion_id):
        if fb_delete(f"camions/{camion_id}"):
            fb_delete(f"positions/{camion_id}")
            afficher_onglet()
            notifier("Camion supprimé", Couleurs.ORANGE)
        else:
            notifier("Suppression impossible. Vérifiez la connexion.", Couleurs.RED)

    def construire_camions():
        corps = ui["corps"]
        camions = fb_get("camions")
        if camions is None:
            corps.controls.append(banniere_erreur())
            return
        zone = ft.Column(spacing=10)

        def carte_camion(cid, info):
            categorie = texte(info.get("categorie"), "Marchandise")
            citerne = categorie == "Citerne"
            chauffeur = texte(info.get("chauffeur_nom"))
            return carte(ft.Column(
                [
                    ft.Row([
                        ft.Container(
                            content=ft.Icon(ic("LOCAL_GAS_STATION") if citerne else ic("LOCAL_SHIPPING"), color=Couleurs.WHITE, size=22),
                            bgcolor=Couleurs.ORANGE if citerne else Couleurs.DARK_BLUE,
                            width=44, height=44, border_radius=22, alignment=ft.alignment.center,
                        ),
                        ft.Column(
                            [
                                ft.Text(cid, weight=ft.FontWeight.BOLD, color=Couleurs.DARK_BLUE, size=15),
                                ft.Text(f"Immatriculation : {texte(info.get('immatriculation'), 'N/A')}", size=12, color=Couleurs.TEXT_GRAY),
                                ft.Text(f"{categorie} • Capacité : {texte(info.get('capacite'), 'N/A')}", size=12, color=Couleurs.TEXT_GRAY),
                                ft.Text(
                                    f"Chauffeur : {chauffeur}" if chauffeur else "Chauffeur : non assigné",
                                    size=12, weight=ft.FontWeight.BOLD,
                                    color=Couleurs.GREEN if chauffeur else Couleurs.RED,
                                ),
                            ],
                            spacing=2, expand=True,
                        ),
                    ]),
                    ft.Divider(height=4),
                    ft.Row(
                        [
                            ft.TextButton("Assigner", icon=ic("LINK"), on_click=lambda e, c=cid, d=info: ouvrir_assignation(c, d, camions)),
                            ft.TextButton("Modifier", icon=ic("EDIT"), on_click=lambda e, c=cid, d=info: ouvrir_formulaire_camion(c, d)),
                            ft.TextButton(
                                "Supprimer", icon=ic("DELETE"),
                                style=ft.ButtonStyle(color=Couleurs.RED),
                                on_click=lambda e, c=cid: confirmer(
                                    "Supprimer ce camion",
                                    f"Supprimer {c} et sa dernière position ? Cette action est définitive.",
                                    lambda: supprimer_camion(c), libelle="Supprimer",
                                ),
                            ),
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_AROUND, wrap=True, spacing=0,
                    ),
                ],
                spacing=6,
            ))

        def maj():
            requete = etat["recherche_camions"].lower()
            elements = []
            for cid, info in sorted(camions.items()):
                if not isinstance(info, dict):
                    continue
                recherche = f"{cid} {info.get('immatriculation', '')} {info.get('chauffeur_nom', '')}".lower()
                if requete and requete not in recherche:
                    continue
                elements.append(carte_camion(cid, info))
            zone.controls = elements or [ft.Text("Aucun camion à afficher.", color=Couleurs.TEXT_GRAY)]
            page.update()

        def sur_recherche(e):
            etat["recherche_camions"] = (e.control.value or "").strip()
            maj()

        corps.controls.extend([
            ft.Row(
                [
                    ft.Text(f"{len(camions)} camion(s)", size=12, color=Couleurs.TEXT_GRAY),
                    bouton("Ajouter", ic("ADD"), Couleurs.YELLOW, lambda e: ouvrir_formulaire_camion(), texte_sombre=True),
                ],
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            ),
            ft.TextField(
                label="Rechercher", prefix_icon=ic("SEARCH"), border_radius=10,
                bgcolor=Couleurs.WHITE, on_change=sur_recherche, value=etat["recherche_camions"],
            ),
            zone,
        ])
        maj()

    # ==========================================
    # ONGLET 3 : CHAUFFEURS
    # ==========================================
    def ouvrir_formulaire_chauffeur(chauffeur_id=None, info=None, chauffeurs=None, camions=None):
        modification = chauffeur_id is not None
        info = info or {}
        chauffeurs = chauffeurs or {}
        camions = camions or {}
        ancien_nom = texte(info.get("nom"))
        f_nom = ft.TextField(label="Nom complet", value=ancien_nom, capitalization=ft.TextCapitalization.WORDS)
        f_tel = ft.TextField(label="Téléphone", value=texte(info.get("telephone")), keyboard_type=ft.KeyboardType.PHONE)
        f_permis = ft.TextField(label="N° de permis", value=texte(info.get("permis")))

        def enregistrer(e):
            nom = (f_nom.value or "").strip()
            tel = (f_tel.value or "").strip()
            if not nom:
                notifier("Le nom est obligatoire.", Couleurs.RED)
                return
            for autre_id, autre in chauffeurs.items():
                if autre_id != chauffeur_id and isinstance(autre, dict) and texte(autre.get("nom")).lower() == nom.lower():
                    notifier("Un chauffeur porte déjà ce nom.", Couleurs.RED)
                    return
            champs = {"nom": nom, "telephone": tel, "permis": (f_permis.value or "").strip()}
            if modification:
                ok = fb_patch(f"chauffeurs/{chauffeur_id}", champs)
                if ok:
                    # répercute le nom et le téléphone sur le camion assigné
                    for camion_id, camion in camions.items():
                        if isinstance(camion, dict) and ancien_nom and camion.get("chauffeur_nom") == ancien_nom:
                            fb_patch(f"camions/{camion_id}", {"chauffeur_nom": nom, "chauffeur_tel": tel})
            else:
                cle = f"chauffeur_{int(datetime.now().timestamp())}"
                ok = fb_put(f"chauffeurs/{cle}", champs)
            if not ok:
                notifier("Échec de l'enregistrement. Vérifiez la connexion.", Couleurs.RED)
                return
            page.close(dlg)
            afficher_onglet()
            notifier("Chauffeur enregistré")

        dlg = ft.AlertDialog(
            modal=True,
            title=ft.Text("Modifier le chauffeur" if modification else "Nouveau chauffeur"),
            content=ft.Column([f_nom, f_tel, f_permis], tight=True, scroll=ft.ScrollMode.AUTO),
            actions=[
                ft.TextButton("Annuler", on_click=lambda e: page.close(dlg)),
                ft.ElevatedButton("Enregistrer", bgcolor=Couleurs.YELLOW, color=Couleurs.DARK_BLUE, on_click=enregistrer),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        page.open(dlg)

    def supprimer_chauffeur(chauffeur_id, nom, camions):
        if not fb_delete(f"chauffeurs/{chauffeur_id}"):
            notifier("Suppression impossible. Vérifiez la connexion.", Couleurs.RED)
            return
        for camion_id, camion in camions.items():
            if isinstance(camion, dict) and camion.get("chauffeur_nom") == nom:
                fb_patch(f"camions/{camion_id}", {"chauffeur_nom": "", "chauffeur_tel": ""})
        afficher_onglet()
        notifier("Chauffeur supprimé", Couleurs.ORANGE)

    def construire_chauffeurs():
        corps = ui["corps"]
        chauffeurs = fb_get("chauffeurs")
        camions = fb_get("camions")
        if chauffeurs is None or camions is None:
            corps.controls.append(banniere_erreur())
            return
        zone = ft.Column(spacing=10)

        def carte_chauffeur(cid, info):
            nom = texte(info.get("nom"), "Sans nom")
            tel = texte(info.get("telephone"))
            camion = next(
                (k for k, c in camions.items() if isinstance(c, dict) and c.get("chauffeur_nom") == nom),
                None,
            )
            boutons = []
            if tel:
                boutons.append(ft.TextButton("Appeler", icon=ic("PHONE"), on_click=lambda e, t=tel: appeler(t)))
            boutons.append(ft.TextButton(
                "Modifier", icon=ic("EDIT"),
                on_click=lambda e, c=cid, d=info: ouvrir_formulaire_chauffeur(c, d, chauffeurs, camions),
            ))
            boutons.append(ft.TextButton(
                "Supprimer", icon=ic("DELETE"), style=ft.ButtonStyle(color=Couleurs.RED),
                on_click=lambda e, c=cid, n=nom: confirmer(
                    "Supprimer ce chauffeur",
                    f"Supprimer {n} ? Il sera aussi retiré du camion auquel il est assigné.",
                    lambda: supprimer_chauffeur(c, n, camions), libelle="Supprimer",
                ),
            ))
            return carte(ft.Column(
                [
                    ft.Row([
                        ft.Container(
                            content=ft.Text(nom[:1].upper(), color=Couleurs.DARK_BLUE, weight=ft.FontWeight.BOLD),
                            bgcolor=Couleurs.YELLOW, width=44, height=44, border_radius=22,
                            alignment=ft.alignment.center,
                        ),
                        ft.Column(
                            [
                                ft.Text(nom, weight=ft.FontWeight.BOLD, color=Couleurs.DARK_BLUE, size=15),
                                ft.Text(f"Téléphone : {texte(tel, 'N/A')}", size=12, color=Couleurs.TEXT_GRAY),
                                ft.Text(f"Permis : {texte(info.get('permis'), 'N/A')}", size=12, color=Couleurs.TEXT_GRAY),
                                ft.Text(
                                    f"Camion : {camion}" if camion else "Camion : non assigné",
                                    size=12, weight=ft.FontWeight.BOLD,
                                    color=Couleurs.GREEN if camion else Couleurs.RED,
                                ),
                            ],
                            spacing=2, expand=True,
                        ),
                    ]),
                    ft.Divider(height=4),
                    ft.Row(boutons, alignment=ft.MainAxisAlignment.SPACE_AROUND, wrap=True, spacing=0),
                ],
                spacing=6,
            ))

        def maj():
            requete = etat["recherche_chauffeurs"].lower()
            elements = []
            tries = sorted(
                [(k, v) for k, v in chauffeurs.items() if isinstance(v, dict)],
                key=lambda x: texte(x[1].get("nom")).lower(),
            )
            for cid, info in tries:
                recherche = f"{info.get('nom', '')} {info.get('telephone', '')}".lower()
                if requete and requete not in recherche:
                    continue
                elements.append(carte_chauffeur(cid, info))
            zone.controls = elements or [ft.Text("Aucun chauffeur à afficher.", color=Couleurs.TEXT_GRAY)]
            page.update()

        def sur_recherche(e):
            etat["recherche_chauffeurs"] = (e.control.value or "").strip()
            maj()

        corps.controls.extend([
            ft.Row(
                [
                    ft.Text(f"{len(chauffeurs)} chauffeur(s)", size=12, color=Couleurs.TEXT_GRAY),
                    bouton(
                        "Ajouter", ic("PERSON_ADD"), Couleurs.YELLOW,
                        lambda e: ouvrir_formulaire_chauffeur(None, None, chauffeurs, camions), texte_sombre=True,
                    ),
                ],
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            ),
            ft.TextField(
                label="Rechercher", prefix_icon=ic("SEARCH"), border_radius=10,
                bgcolor=Couleurs.WHITE, on_change=sur_recherche, value=etat["recherche_chauffeurs"],
            ),
            zone,
        ])
        maj()

    # ==========================================
    # RÉGLAGES ET SÉCURITÉ
    # ==========================================
    def lire_pin():
        try:
            return page.client_storage.get(CLE_PIN) or PIN_PAR_DEFAUT
        except Exception:
            return PIN_PAR_DEFAUT

    def ecrire_pin(pin):
        try:
            page.client_storage.set(CLE_PIN, pin)
            return True
        except Exception:
            return False

    def ouvrir_changement_pin(e=None):
        f_ancien = ft.TextField(label="Ancien PIN", password=True, can_reveal_password=True, keyboard_type=ft.KeyboardType.NUMBER)
        f_nouveau = ft.TextField(label="Nouveau PIN (4 chiffres minimum)", password=True, can_reveal_password=True, keyboard_type=ft.KeyboardType.NUMBER)
        f_confirm = ft.TextField(label="Confirmer le nouveau PIN", password=True, can_reveal_password=True, keyboard_type=ft.KeyboardType.NUMBER)

        def valider(ev):
            if f_ancien.value != lire_pin():
                notifier("Ancien PIN incorrect.", Couleurs.RED)
                return
            nouveau = f_nouveau.value or ""
            if len(nouveau) < 4 or not nouveau.isdigit():
                notifier("Le nouveau PIN doit contenir au moins 4 chiffres.", Couleurs.RED)
                return
            if nouveau != f_confirm.value:
                notifier("Les deux PIN ne correspondent pas.", Couleurs.RED)
                return
            if not ecrire_pin(nouveau):
                notifier("Impossible d'enregistrer le PIN sur cet appareil.", Couleurs.RED)
                return
            page.close(dlg)
            notifier("PIN modifié")

        dlg = ft.AlertDialog(
            modal=True,
            title=ft.Text("Changer le PIN"),
            content=ft.Column([f_ancien, f_nouveau, f_confirm], tight=True),
            actions=[
                ft.TextButton("Annuler", on_click=lambda ev: page.close(dlg)),
                ft.ElevatedButton("Valider", bgcolor=Couleurs.YELLOW, color=Couleurs.DARK_BLUE, on_click=valider),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        page.open(dlg)

    # ==========================================
    # NAVIGATION
    # ==========================================
    def afficher_onglet():
        corps = ui["corps"]
        ui["maj_suivi"] = None
        ui["sous_titre"].value = TITRES[etat["onglet"]]
        corps.controls = [ft.Row([ft.ProgressRing(width=28, height=28)], alignment=ft.MainAxisAlignment.CENTER)]
        page.update()
        corps.controls = []
        [construire_suivi, construire_camions, construire_chauffeurs][etat["onglet"]]()
        corps.controls.append(ft.Container(height=20))
        page.update()

    def changer_onglet(e):
        etat["onglet"] = e.control.selected_index
        afficher_onglet()

    def verrouiller(e=None):
        etat["actif"] = False
        afficher_login()

    def afficher_app():
        page.clean()
        etat["actif"] = True
        ui["corps"] = ft.Column(spacing=12, scroll=ft.ScrollMode.AUTO, expand=True)
        ui["sous_titre"] = ft.Text("", size=12, color=Couleurs.YELLOW)

        entete = ft.Container(
            bgcolor=Couleurs.DARK_BLUE,
            padding=ft.padding.only(left=20, right=4, top=8, bottom=14),
            content=ft.Row([
                ft.Column(
                    [ft.Text("K-HAIM PATRON", size=20, weight=ft.FontWeight.BOLD, color=Couleurs.WHITE), ui["sous_titre"]],
                    spacing=2, expand=True,
                ),
                ft.IconButton(ic("KEY"), icon_color=Couleurs.YELLOW, tooltip="Changer le PIN", on_click=ouvrir_changement_pin),
                ft.IconButton(ic("LOCK"), icon_color=Couleurs.YELLOW, tooltip="Verrouiller", on_click=verrouiller),
            ]),
        )
        page.navigation_bar = ft.NavigationBar(
            selected_index=etat["onglet"],
            bgcolor=Couleurs.WHITE,
            on_change=changer_onglet,
            destinations=[
                ft.NavigationBarDestination(icon=ic("LOCATION_ON"), label="Suivi"),
                ft.NavigationBarDestination(icon=ic("LOCAL_SHIPPING"), label="Camions"),
                ft.NavigationBarDestination(icon=ic("PEOPLE"), label="Chauffeurs"),
            ],
        )
        page.add(
            ft.SafeArea(
                expand=True,
                content=ft.Column(
                    [
                        entete,
                        ft.Container(
                            content=ui["corps"], bgcolor=Couleurs.BG_GRAY, expand=True,
                            padding=ft.padding.only(left=16, right=16, top=14),
                        ),
                    ],
                    spacing=0, expand=True,
                ),
            )
        )
        afficher_onglet()

    def afficher_login():
        page.clean()
        page.navigation_bar = None
        pin = ft.TextField(
            label="Code PIN", password=True, can_reveal_password=True,
            keyboard_type=ft.KeyboardType.NUMBER, width=260, text_align=ft.TextAlign.CENTER,
            border_radius=10, filled=True, bgcolor=Couleurs.WHITE, color=Couleurs.DARK_BLUE,
        )

        def valider(e):
            if pin.value == lire_pin():
                afficher_app()
            else:
                pin.value = ""
                pin.error_text = "Code incorrect"
                page.update()

        pin.on_submit = valider
        page.add(
            ft.SafeArea(
                expand=True,
                content=ft.Column(
                    [
                        ft.Icon(ic("ADMIN_PANEL_SETTINGS"), size=72, color=Couleurs.YELLOW),
                        ft.Text("K-HAIM PATRON", size=26, weight=ft.FontWeight.BOLD, color=Couleurs.WHITE),
                        ft.Text("Gestion de la flotte", size=13, color=Couleurs.WHITE),
                        ft.Container(height=30),
                        pin,
                        ft.Container(height=10),
                        bouton("Ouvrir", ic("LOCK_OPEN"), Couleurs.YELLOW, valider, texte_sombre=True, width=260),
                    ],
                    alignment=ft.MainAxisAlignment.CENTER,
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    expand=True,
                ),
            )
        )
        page.update()

    # actualisation automatique de l'onglet Suivi
    def boucle_actualisation():
        while True:
            time.sleep(ACTUALISATION_SEC)
            try:
                if etat["actif"] and etat["auto"] and etat["onglet"] == 0 and ui["maj_suivi"]:
                    ui["maj_suivi"]()
            except Exception:
                pass

    threading.Thread(target=boucle_actualisation, daemon=True).start()
    afficher_login()


def main(page: ft.Page):
    try:
        main_app(page)
    except Exception:
        page.add(ft.Text(traceback.format_exc(), selectable=True, color="red"))
        page.update()


ft.app(target=main)

