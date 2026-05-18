"""
Calibrage BITalino — Interface CRT responsive (package).

Ordre de calibration :
  0. DÉTECTION  : ouverture de la carte BITalino (sinon RÉESSAYER / DÉMO).
  1. REPOS+CŒUR : accéléromètre immobile → le port PPG (oreille) est isolé
                  EN PREMIER par sa périodicité (seule courbe qui bouge).
  2. RYTHME CARDIAQUE : BPM de repos affiné sur le port PPG isolé.
  3. GAUCHE / DROITE  : axe X = port à plus forte variance (vs repos).
  4. HAUT / BAS       : axes Y puis Z (ports restants, hors PPG).
  5. MUSCLE / EMG     : EMG EN DERNIER — PPG + axes accéléro connus, le
                        port EMG est isolé par élimination (capteur faible).
  6. ZONE MORTE       : zone morte accéléro + EMG (seuil + curseur
                        d'amplification, jauge EMG), inverseurs G/D
                        et H/B, éditeur ports [PORTS], recalibrage
                        ciblé [RECAL 1] (1 capteur, autres gardés).
                        (Pas de zone morte cardiaque.)

Sortie : calibration.json.

Lancement :
    python calibrage.py [adresse]
    python calibrage.py --demo
"""

from .app import main

__all__ = ["main"]
