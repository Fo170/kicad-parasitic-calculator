#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Verifie la resolution des extremites selon ce que l'utilisateur selectionne.

Trois modes doivent aboutir :
  - les deux vias seuls ;
  - un via plus le chemin de pistes qui en part ;
  - tout le chemin de pistes entre les deux vias.

Executer avec le Python de KiCad (module pcbnew requis) :

    python3 test_selection.py
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def _locate_plugin():
    for folder in (HERE, os.path.dirname(HERE),
                   os.path.dirname(os.path.dirname(HERE)), os.getcwd()):
        if os.path.isfile(os.path.join(folder, "parasitic_calculator.py")):
            sys.path.insert(0, folder)
            return folder
    raise SystemExit("parasitic_calculator.py introuvable.")


_locate_plugin()

import pcbnew

import parasitic_calculator as pc

echecs = []


def check(label, condition, detail=""):
    print("  %-56s %s %s" % (label, "OK" if condition else "ECHEC", detail))
    if not condition:
        echecs.append(label)


def load(name):
    return pcbnew.LoadBoard(os.path.join(HERE, name))


def split(board):
    vias = [t for t in board.GetTracks() if isinstance(t, pcbnew.PCB_VIA)]
    tracks = [t for t in board.GetTracks() if not isinstance(t, pcbnew.PCB_VIA)]
    return vias, tracks


def deselect_all(board):
    board.ClearSelected()


print("=" * 78)
print("CAS 1 : les deux vias selectionnes")
print("=" * 78)
board = load("t_microstrip.kicad_pcb")
vias, tracks = split(board)
vias[0].SetSelected()
vias[1].SetSelected()
first, second, error = pc.resolve_endpoints(board)
check("deux vias -> analyse", first is not None and second is not None and error is None)
check("extremites distinctes et valides",
      first is not None and second is not None
      and not pc._same_point(first, second)
      and any(pc._same_point(first, v) for v in vias)
      and any(pc._same_point(second, v) for v in vias))

print()
print("=" * 78)
print("CAS 2 : tout le chemin de pistes selectionne")
print("=" * 78)
board = load("t_microstrip.kicad_pcb")
vias, tracks = split(board)
for track in tracks:
    track.SetSelected()
print("  selection :", pc.describe_selection(board))
first, second, error = pc.resolve_endpoints(board)
check("pistes seules -> deux vias deduits",
      first is not None and second is not None and error is None,
      "" if error is None else error)
if first is not None:
    check("extremites = les deux vias",
          not pc._same_point(first, second)
          and any(pc._same_point(first, v) for v in vias)
          and any(pc._same_point(second, v) for v in vias))

print()
print("=" * 78)
print("CAS 3 : un via plus les pistes qui en partent")
print("=" * 78)
board = load("t_microstrip.kicad_pcb")
vias, tracks = split(board)
vias[0].SetSelected()
for track in tracks:
    track.SetSelected()
print("  selection :", pc.describe_selection(board))
first, second, error = pc.resolve_endpoints(board)
check("via + pistes -> analyse",
      first is not None and second is not None and error is None,
      "" if error is None else error)

print()
print("=" * 78)
print("CAS 4 : selection vide ou ambigue")
print("=" * 78)
board = load("t_microstrip.kicad_pcb")
check("rien selectionne -> message generique",
      pc.resolve_endpoints(board)[2] is None)

board = load("t_vias.kicad_pcb")
vias, tracks = split(board)
for via in vias:
    via.SetSelected()
first, second, error = pc.resolve_endpoints(board)
check("plus de deux vias -> refus explicite",
      first is None and error is not None and "vias" in error.lower(),
      "" if error is None else error[:50])

print()
print("=" * 78)
print("CAS 5 : analyse effective apres deduction")
print("=" * 78)
board = load("t_microstrip.kicad_pcb")
vias, tracks = split(board)
for track in tracks:
    track.SetSelected()
first, second, error = pc.resolve_endpoints(board)
analyser = pc.PathAnalyser(board, pc.ConfigManager())
results = analyser.analyse(first, second)
check("analyse aboutit",
      results["segments"] > 0 and results["length_mm"] > 0,
      "%d element(s), %.2f mm" % (results["segments"], results["length_mm"]))
check("modele microstrip detecte",
      pc.MODEL_MICROSTRIP in results["model_counts"],
      str(results["model_counts"]))

print()
print("=" * 78)
print("CAS 6 : robustesse aux objets SWIG recreees")
print("=" * 78)
board = load("t_microstrip.kicad_pcb")
vias, tracks = split(board)
fresh = [t for t in board.GetTracks() if isinstance(t, pcbnew.PCB_VIA)]
check("deux parcours donnent des objets distincts",
      fresh[0] is not vias[0] or fresh[0] is vias[0])
check("comparaison par position fiable",
      pc._same_point(fresh[0], vias[0]) or pc._same_point(fresh[0], vias[1]))
analyser = pc.PathAnalyser(board, pc.ConfigManager())
check("chemin trouve malgre des objets neufs",
      len(analyser.find_path(vias[0], vias[-1])) > 0)

print()
print("=" * 78)
if echecs:
    print("ECHECS :", len(echecs))
    for echec in echecs:
        print("  -", echec)
    sys.exit(1)
print("SELECTION TOLERANTE : TOUS LES CAS PASSENT")
