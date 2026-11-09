"""Jours fériés en France métropolitaine et échéances en jours calendaires.

Le CCAG Travaux 2021 compte les délais en jours calendaires ; un délai qui expire un samedi,
un dimanche ou un jour férié est prolongé jusqu'à la fin du premier jour ouvrable qui suit.
"""
from __future__ import annotations

import datetime
from functools import lru_cache


def paques(annee: int) -> datetime.date:
    """Dimanche de Pâques (algorithme de Meeus/Jones/Butcher)."""
    a, b, c = annee % 19, annee // 100, annee % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7  # noqa: E741
    m = (a + 11 * h + 22 * l) // 451
    mois = (h + l - 7 * m + 114) // 31
    jour = (h + l - 7 * m + 114) % 31 + 1
    return datetime.date(annee, mois, jour)


@lru_cache(maxsize=64)
def jours_feries(annee: int) -> frozenset[datetime.date]:
    dimanche = paques(annee)
    return frozenset({
        datetime.date(annee, 1, 1), dimanche + datetime.timedelta(days=1), datetime.date(annee, 5, 1), datetime.date(annee, 5, 8),
        dimanche + datetime.timedelta(days=39), dimanche + datetime.timedelta(days=50), datetime.date(annee, 7, 14),
        datetime.date(annee, 8, 15), datetime.date(annee, 11, 1), datetime.date(annee, 11, 11), datetime.date(annee, 12, 25),
    })


def ouvrable(jour: datetime.date) -> bool:
    return jour.weekday() < 5 and jour not in jours_feries(jour.year)


def echeance(depart: datetime.date, jours: int) -> datetime.date:
    """Départ + `jours` calendaires, reporté au premier jour ouvrable."""
    fin = depart + datetime.timedelta(days=jours)
    while not ouvrable(fin):
        fin += datetime.timedelta(days=1)
    return fin
