# PitLane FM Racing

Snapshot source propre de la branche `racing` de PitLane FM, préparé pour un dépôt GitHub.

## Contenu

Ce dossier contient uniquement :

- `Nouvelle structure de dev Racing`
  - apps racing : `ACC`, `AMS2`, `LMU`, `ACE`
  - outils de build liés à la branche racing
- `liste_m3u_Bloc11.txt`
  - liste des radios intégrées avec leur nom de source et leur URL de flux

Les répertoires de build, les binaires générés, les logs locaux et les installers compilés ont été retirés de cette version GitHub.

## Prérequis

- Windows
- Python `3.12`
- [Inno Setup 6](https://www.innosetup.com/) pour les setups
- dépendances Python du fichier `requirements.txt`

Installation rapide :

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## Dépendances Python

Le projet utilise principalement :

- `pygame`
- `psutil`
- `miniaudio`
- `Pillow`
- `comtypes`
- `pyaccsharedmemory`

## Build

Chaque application garde son script de compilation dédié dans `Bloc12`.

Exemples :

```powershell
python ".\Nouvelle structure de dev Racing\Bloc12\ACE\compi.py"
python ".\Nouvelle structure de dev Racing\Bloc12\ACC\compi.py"
python ".\Nouvelle structure de dev Racing\Bloc12\AMS2\compi.py"
python ".\Nouvelle structure de dev Racing\Bloc12\LMU\compi.py"
```

## Radios intégrées

Pour faciliter la review, la liste des fichiers `.m3u` embarqués et leurs sources de flux est fournie ici :

- `liste_m3u_Bloc11.txt`

## Ce qui a été exclu

- `build/`
- `dist/`
- `output/`
- `__pycache__/`
- `logs/`
- `crashdumps/`
- fichiers `.exe`
- archives `.zip`

## Licence

Ce dépôt est distribué sous une licence propriétaire personnalisée.

Résumé simple :

- pas d'utilisation commerciale
- pas de republication, reupload, miroir ou redistribution sur un autre site sans autorisation écrite préalable

Voir [LICENSE.md](./LICENSE.md) pour le texte complet.

Note pratique :
si tu publies ce dépôt en **public** sur GitHub, les utilisateurs GitHub pourront quand même le consulter et le forker via les fonctionnalités normales de la plateforme. Si tu veux un contrôle plus strict de la diffusion, privilégie un dépôt **privé**.

## Structure rapide

```text
PitLane-FM-Racing-GitHub/
├── README.md
├── LICENSE.md
├── requirements.txt
├── .gitignore
├── .gitattributes
└── Nouvelle structure de dev Racing/
```
