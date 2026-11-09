"""Contrôle du DCE avant diffusion : ce qui manque ou reste à compléter."""
from __future__ import annotations

from projets.champs import champs_du_projet, champs_utilises, consultation_du_projet
from projets.models import GenrePoste, Projet, TypePiece

from .models import CategoriePieceJointe, PieceJointe

OK, ALERTE, MANQUE = "OK", "ALERTE", "MANQUE"


def _point(niveau: str, texte: str, lien: str = "") -> dict:
    return {"niveau": niveau, "texte": texte, "lien": lien}


def controler(projet: Projet) -> list[dict]:
    points: list[dict] = []
    lien_projet = f"/projets/{projet.pk}"
    pieces = {(p.type_piece, p.lot_id): p for p in projet.pieces.prefetch_related("clauses")}
    lots = list(projet.lots.order_by("ordre", "code"))

    if not lots:
        points.append(_point(MANQUE, "Le projet n'a aucun lot.", lien_projet))

    for type_piece, nom in [(TypePiece.RC, "Règlement de la consultation"), (TypePiece.CCAP, "CCAP")]:
        piece = pieces.get((type_piece, None))
        if piece is None:
            points.append(_point(MANQUE, f"{nom} non rédigé : il ne figurera pas dans le DCE.", lien_projet))
        else:
            points.append(_point(OK, f"{nom} rédigé ({piece.clauses.count()} clauses).", f"{lien_projet}/pieces/{piece.pk}"))

    champs_manquants: dict[str, set[str]] = {}
    for piece in pieces.values():
        champs = champs_du_projet(projet, piece.lot)
        utilises = champs_utilises([c.titre for c in piece.clauses.all()] + [c.contenu for c in piece.clauses.all()])
        for cle in utilises:
            champ = champs.get(cle)
            libelle = champ.libelle if champ else f"champ inconnu « {cle} »"
            if champ is None or not champ.renseigne:
                champs_manquants.setdefault(libelle, set()).add(piece.get_type_piece_display() if piece.lot is None else f"AE lot {piece.lot.code}")
    for libelle, ou in sorted(champs_manquants.items()):
        points.append(_point(ALERTE, f"« {libelle} » à compléter (utilisé dans : {', '.join(sorted(ou))}).", lien_projet))

    for lot in lots:
        prefixe = f"Lot {lot.code} – {lot.intitule}"
        postes = list(lot.postes.all())
        ouvrages = [p for p in postes if p.genre == GenrePoste.OUVRAGE]
        if not postes:
            points.append(_point(MANQUE, f"{prefixe} : CCTP et DPGF vides.", f"{lien_projet}/lots/{lot.pk}"))
        else:
            sans_quantite = [p for p in ouvrages if p.quantite is None]
            if not ouvrages:
                points.append(_point(ALERTE, f"{prefixe} : aucun ouvrage chiffrable, la DPGF ne sera pas jointe.", f"{lien_projet}/lots/{lot.pk}"))
            elif sans_quantite:
                points.append(_point(ALERTE, f"{prefixe} : {len(sans_quantite)} ouvrage(s) sans quantité dans la DPGF.", f"{lien_projet}/lots/{lot.pk}"))
            else:
                points.append(_point(OK, f"{prefixe} : CCTP et DPGF prêts ({len(ouvrages)} ouvrages).", f"{lien_projet}/lots/{lot.pk}"))
        if (TypePiece.AE, lot.pk) not in pieces:
            points.append(_point(MANQUE, f"{prefixe} : acte d'engagement non rédigé.", lien_projet))

    consultation = consultation_du_projet(projet)
    if not consultation.date_limite_offres:
        points.append(_point(ALERTE, "Date limite de remise des offres non renseignée.", lien_projet))
    if projet.type_marche == "PUBLIC" and not consultation.profil_acheteur:
        points.append(_point(ALERTE, "Profil d'acheteur (plateforme de publication) non renseigné.", lien_projet))
    if not PieceJointe.objects.filter(projet=projet, categorie=CategoriePieceJointe.PLANS).exists():
        points.append(_point(ALERTE, "Aucun plan joint au DCE.", ""))
    return points
