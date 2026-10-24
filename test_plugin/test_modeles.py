#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Verifie que chaque carte de test donne le modele de ligne attendu.

Executer avec le Python de KiCad (module pcbnew requis) :

    python3 test_modeles.py
"""

import glob
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def _locate_plugin():
    """Ajoute au chemin le dossier contenant parasitic_calculator.py."""
    candidates = [
        HERE,
        os.path.dirname(HERE),
        os.path.dirname(os.path.dirname(HERE)),
        os.getcwd(),
    ]
    for folder in candidates:
        if os.path.isfile(os.path.join(folder, "parasitic_calculator.py")):
            sys.path.insert(0, folder)
            return folder
    raise SystemExit(
        "parasitic_calculator.py introuvable.\n"
        "Placez ce script dans le dossier test_plugin du depot, ou copiez le "
        "plugin a cote.")


_locate_plugin()

import pcbnew

import parasitic_calculator as pc

ATTENDU = {
    "t_microstrip.kicad_pcb": {pc.MODEL_MICROSTRIP},
    "t_stripline.kicad_pcb": {pc.MODEL_STRIPLINE},
    "t_stripline_asym.kicad_pcb": {pc.MODEL_STRIPLINE_ASYM},
    "t_cpw.kicad_pcb": {pc.MODEL_CPW},
    "t_cpwg.kicad_pcb": {pc.MODEL_CPWG},
    "t_vias.kicad_pcb": {pc.MODEL_ISOLATED},
    "t_no_fake_path.kicad_pcb": None,
    "t_ground_match.kicad_pcb": {pc.MODEL_MICROSTRIP},
    "t_piste_isolee.kicad_pcb": {pc.MODEL_ISOLATED},
}

VIAS_CHAIN = {"t_vias.kicad_pcb": 5}

echecs = []


def vias_of(board, name):
    vias = sorted([t for t in board.GetTracks() if isinstance(t, pcbnew.PCB_VIA)],
                  key=lambda v: v.GetPosition().x)
    if name in VIAS_CHAIN:
        vias = vias[:VIAS_CHAIN[name]]
    return vias


print("=" * 78)
print("MODELES DE LIGNE PAR CARTE")
print("=" * 78)

for path in sorted(glob.glob(os.path.join(HERE, "t_*.kicad_pcb"))):
    name = os.path.basename(path)
    board = pcbnew.LoadBoard(path)
    analyser = pc.PathAnalyser(board, pc.ConfigManager())
    vias = vias_of(board, name)
    attendu = ATTENDU.get(name)

    footprints = len(list(board.GetFootprints()))
    comments = len([d for d in board.GetDrawings() if d.GetLayer() == pcbnew.Cmts_User])
    outline = len([d for d in board.GetDrawings() if d.GetLayer() == pcbnew.Edge_Cuts])

    if footprints < 2 or comments < 1 or outline < 4:
        echecs.append((name, "carte incomplete", "fp=%d cmt=%d edge=%d"
                       % (footprints, comments, outline)))

    try:
        results = analyser.analyse(vias[0], vias[-1])
    except ValueError:
        if attendu is None:
            print("%-28s fp=%d cmt=%d edge=%d  %-40s OK (refus attendu)" % (
                name, footprints, comments, outline, "-"))
        else:
            print("%-28s fp=%d cmt=%d edge=%d  %-40s ECHEC (refus inattendu)" % (
                name, footprints, comments, outline, "-"))
            echecs.append((name, attendu, "refus inattendu"))
        continue

    modeles = set(results["model_counts"])
    if attendu is None:
        verdict = "ECHEC (chemin accepte)"
        echecs.append((name, "devait refuser", modeles))
    elif modeles == attendu:
        verdict = "OK"
    else:
        verdict = "ECHEC"
        echecs.append((name, attendu, modeles))

    print("%-28s fp=%d cmt=%d edge=%d  %-40s %s" % (
        name, footprints, comments, outline, str(results["model_counts"]), verdict))

    for record in [r for r in results["records"] if r["kind"] == "track"]:
        if record["c"] > 0 and record["l"] > 0:
            z_calc = (record["l"] / record["c"]) ** 0.5
            z_ref = record["geometry"]["z0"]
            ecart = abs(z_calc - z_ref) / z_ref * 100.0
            if ecart >= 0.5:
                echecs.append((name, "coherence Z0=sqrt(L/C)", "%.3f%%" % ecart))

print()
print("=" * 78)
print("TYPES DE VIAS")
print("=" * 78)

board = pcbnew.LoadBoard(os.path.join(HERE, "t_vias.kicad_pcb"))
analyser = pc.PathAnalyser(board, pc.ConfigManager())
vias = sorted([t for t in board.GetTracks() if isinstance(t, pcbnew.PCB_VIA)],
              key=lambda v: v.GetPosition().x)
attendus = [pc.VIA_THROUGH, pc.VIA_BLIND, pc.VIA_BURIED, pc.VIA_BLIND,
            pc.VIA_THROUGH, pc.VIA_MICROVIA]
trouves = []
for via in vias:
    kind, _, _ = analyser.via_kind(via)
    record = analyser.via_record(via)
    trouves.append(kind)
    print("  x=%5.1f  %-11s %-7s -> %-7s  fut=%.3f mm  R=%s  L=%s  C=%s" % (
        pcbnew.ToMM(via.GetPosition().x), kind, record["layer_top"],
        record["layer_bottom"], record["span_mm"],
        pc.fmt_value(record["r_dc"]), pc.fmt_value(record["l"]),
        pc.fmt_value(record["c"])))
if trouves != attendus:
    echecs.append(("t_vias", attendus, trouves))

print()
print("=" * 78)
if echecs:
    print("ECHECS :", len(echecs))
    for echec in echecs:
        print("  -", echec)
    sys.exit(1)
print("TOUS LES TESTS PASSENT")
