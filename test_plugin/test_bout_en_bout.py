#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Analyse complete de plusieurs cartes et controle de coherence.

Executer avec le Python de KiCad (module pcbnew requis) :

    python3 test_bout_en_bout.py
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

CAS = [
    ("t_microstrip.kicad_pcb", "microstrip, 2 couches", None),
    ("t_stripline.kicad_pcb", "stripline symetrique, 4 couches", None),
    ("t_stripline_asym.kicad_pcb", "stripline asymetrique, 6 couches", None),
    ("t_cpwg.kicad_pcb", "coplanaire avec plan arriere, 4 couches", None),
    ("t_piste_isolee.kicad_pcb", "piste isolee, aucun plan", None),
    ("t_vias.kicad_pcb", "chaine de vias de types differents", 5),
]

echecs = []
for fichier, libelle, limite in CAS:
    path = os.path.join(HERE, fichier)
    print("=" * 78)
    print("%s (%s)" % (libelle, fichier))

    board = pcbnew.LoadBoard(path)
    analyser = pc.PathAnalyser(board, pc.ConfigManager())
    vias = sorted([t for t in board.GetTracks() if isinstance(t, pcbnew.PCB_VIA)],
                  key=lambda v: v.GetPosition().x)
    if limite:
        vias = vias[:limite]

    try:
        results = analyser.analyse(vias[0], vias[-1])
    except ValueError as exc:
        print("  ECHEC :", exc)
        echecs.append((fichier, str(exc)))
        continue

    print("  R_DC=%s  R_AC=%s  L=%s  C=%s  Z0=%.2f Ohm  Td=%s" % (
        pc.fmt_value(results["resistance_ohm"]),
        pc.fmt_value(results["resistance_ac_ohm"]),
        pc.fmt_value(results["inductance_h"]),
        pc.fmt_value(results["capacitance_f"]),
        results["impedance_ohm"],
        pc.fmt_value(results["delay_s"])))
    print("  elements=%d  vias=%d  modeles=%s  types de via=%s" % (
        results["segments"], results["via_count"],
        results["model_counts"], results["via_counts"]))

    controles = [
        ("via_count coherent", results["via_count"] == len(vias)),
        ("segments coherent", results["segments"] == len(results["records"])),
        ("longueur positive", results["length_mm"] > 0),
        ("inductance positive", results["inductance_h"] > 0),
        ("details non vides", len(results["details"]) > 0),
        ("resistance positive", results["resistance_ohm"] > 0),
    ]
    for libelle_controle, ok in controles:
        if not ok:
            echecs.append((fichier, libelle_controle))
            print("  ECHEC :", libelle_controle)
    if all(ok for _, ok in controles):
        print("  -> OK")

print()
print("=" * 78)
if echecs:
    print("ECHECS :", len(echecs))
    for echec in echecs:
        print("  -", echec)
    sys.exit(1)
print("BOUT EN BOUT : TOUT PASSE")
