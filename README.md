# Tetrino

## Description

Ce projet consiste en une adaptation du jeu Tetris utilisant des données physiologiques acquises avec un dispositif BITalino. Les mesures de rythme cardiaque (PPG) et d'activité électrodermale (EDA) sont utilisées pour estimer le niveau de stress de l'utilisateur et ajuster dynamiquement la vitesse de chute des pièces tandis que l'accéléromètre permet une utilisation de l'application inhabituelle.

## Fonctionnalités

- Jeu Tetris développé avec Pygame.
- Acquisition des données physiologiques via BITalino.
- Calcul d'un indicateur de stress à partir des signaux PPG et EDA.
- Adaptation automatique de la difficulté du jeu en fonction de l'état physiologique de l'utilisateur.

## Prérequis

### Matériel

- BITalino
- Capteur PPG
- Capteur EDA
- Ordinateur compatible Bluetooth

### Logiciel

- Python 3.10
- pip

## Installation

### 1. Cloner le dépôt

```bash
git clone https://github.com/Gasthorn/2026_4ATechFacHum_Brault_Bourdas.git
cd 2026_4ATechFacHum_Brault_Bourdas
```

### 2. Configuration

Avant de lancer l'aplpication, modifier l'adresse Bluetooth du BITalino dans le fichier :
```bash
BITALINO_MAC = "XX:XX:XX:XX:XX:XX"
```

### 3. Lancement

Depuis la racine du projet :
```bash
python main.py
```

### Utilisation

- Connecter les trois capteurs au BITalino.
- Vérifier que le Bluetooth est activé.
- Lancer l'application.
- Réaliser la phase de calibration.
- Jouer au Tetris.
- Observer l'adaptation du niveau de difficulté en fonction des mesures physiologiques.

