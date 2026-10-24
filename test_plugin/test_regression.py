#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Verifie que chaque bug corrige le reste (non-regression).

Executer avec le Python de KiCad (module pcbnew requis) :

    python3 test_regression.py
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


PLUGIN_DIR = _locate_plugin()

import pcbnew

import parasitic_calculator as pc

resultats = []


def verify(finding, description, condition, detail=""):
    statut = "CORRIGE" if condition else "TOUJOURS PRESENT"
    resultats.append((finding, description, statut, detail))
    print("  %-9s %-56s %-16s %s" % (finding, description, statut, detail))


def board(name):
    return pcbnew.LoadBoard(os.path.join(HERE, name))


def sorted_vias(loaded):
    return sorted([t for t in loaded.GetTracks() if isinstance(t, pcbnew.PCB_VIA)],
                  key=lambda v: v.GetPosition().x)


source = open(os.path.join(PLUGIN_DIR, "parasitic_calculator.py")).read()

print("=" * 100)
print("NON-REGRESSION DES BUGS CORRIGES")
print("=" * 100)

verify("N1", "IU_PER_MM compatible KiCad 7 a 10",
       pc.IU_PER_MM == 1000000.0, "%.0f" % pc.IU_PER_MM)

verify("N2", "Nom de couche sans pcbnew.Board",
       pc.layer_name(pcbnew.F_Cu) == "F.Cu", pc.layer_name(pcbnew.F_Cu))

verify("N3", "BFS sans objets KiCad comme cles de dictionnaire",
       "id(start_via)" in source, "indices id()")

verify("N4", "list(GetCopperLayerCount()) supprime",
       "list(settings.GetCopperLayerCount())" not in source, "")

stripline = board("t_stripline.kicad_pcb")
analyser = pc.PathAnalyser(stripline, pc.ConfigManager())
verify("R02", "Empilement construit depuis les couches reelles",
       len(analyser.stackup.layers) == 4, "%d couches" % len(analyser.stackup.layers))

vias = sorted_vias(stripline)
records = analyser.analyse(vias[0], vias[-1])["records"]
via_records = [r for r in records if r["kind"] == "via"]
verify("R01", "Vias traites comme vias, pas comme pistes",
       len(via_records) == 2 and all("via_kind" in r for r in via_records),
       "%d vias" % len(via_records))

micro = board("t_microstrip.kicad_pcb")
analyser_micro = pc.PathAnalyser(micro, pc.ConfigManager())
attendu = (1.6 - 2 * 0.035) / 1
verify("R07", "Dielectrique = (t_total - n*t_cu)/(n-1)",
       abs(analyser_micro.stackup.h - attendu) < 1e-6,
       "%.4f mm" % analyser_micro.stackup.h)

calc = pc.ParasiticCalculator(pc.ConfigManager())
z0 = calc.z0_microstrip(0.3e-3, 1.53e-3)
eps_eff = calc.eps_eff_microstrip(0.3e-3, 1.53e-3)
inductance, capacitance = calc.lc_from_z0(z0, eps_eff, 0.02)
coherent = (abs((inductance / capacitance) ** 0.5 - z0) < 1e-6
            and abs(inductance * capacitance
                    / (eps_eff * (0.02 / pc.C_LUMIERE) ** 2) - 1) < 1e-9)
verify("R04", "L, C et Z0 issus du meme modele de ligne",
       coherent, "Z0 = %.2f Ohm" % z0)

ground = board("t_ground_match.kicad_pcb")
analyser_ground = pc.PathAnalyser(ground, pc.ConfigManager())
noms = [n.GetNetname() for n in ground.GetNetsByName().values()
        if n.GetNetCode() in analyser_ground.model.ground_nets]
verify("R08", "Nets de masse en egalite exacte (+3V3 exclu)",
       "+3V3" not in noms and "GND" in noms, str(noms))

config_vide = pc.ConfigManager()
config_vide.set("ground_net_names", [])
verify("R08b", "Liste de nets vide ne detecte rien",
       len(pc.BoardModel(ground, config_vide).ground_nets) == 0, "0 net")

config_off = pc.ConfigManager()
config_off.set("detect_reference_planes", False)
config_off.set("default_dielectric_mm", 0.2)
analyser_off = pc.PathAnalyser(micro, config_off)
piste = [t for t in micro.GetTracks() if not isinstance(t, pcbnew.PCB_VIA)][0]
geo_off = analyser_off.select_model(piste.GetLayer(), piste.GetStart(), 0.3)
geo_on = analyser_micro.select_model(piste.GetLayer(), piste.GetStart(), 0.3)
verify("R09", "Option de detection des plans sans effet fantome",
       abs(geo_off["height_mm"] - 0.2) < 1e-9
       and abs(geo_on["height_mm"] - 1.53) < 1e-6,
       "off=%.2f on=%.2f" % (geo_off["height_mm"], geo_on["height_mm"]))

faux = board("t_no_fake_path.kicad_pcb")
analyser_faux = pc.PathAnalyser(faux, pc.ConfigManager())
vias_faux = sorted_vias(faux)
verify("R10", "Chemin refuse entre couches differentes",
       len(analyser_faux.find_path(vias_faux[0], vias_faux[-1])) == 0, "0 element")

verify("R12", "Plus de 'except:' nu",
       "\n        except:\n" not in source, "")

config_chaud = pc.ConfigManager()
config_chaud.set("temp_c", 100.0)
r_chaud = pc.ParasiticCalculator(config_chaud).via_resistance(0.6, 0.3, 1.6)
r_froid = pc.ParasiticCalculator(pc.ConfigManager()).via_resistance(0.6, 0.3, 1.6)
rapport = r_chaud / r_froid
attendu_rapport = (1 + 0.00393 * 80) / (1 + 0.00393 * 5)
verify("R13", "Resistance de via corrigee en temperature",
       abs(rapport - attendu_rapport) < 1e-6, "x%.4f" % rapport)

vias_board = board("t_vias.kicad_pcb")
analyser_vias = pc.PathAnalyser(vias_board, pc.ConfigManager())
spans = {}
for via in sorted_vias(vias_board):
    kind, top, bottom = analyser_vias.via_kind(via)
    spans.setdefault(kind, set()).add(round(analyser_vias.stackup.span_length(top, bottom), 3))
verify("R14", "Longueur de via = span reel",
       spans.get(pc.VIA_THROUGH) == {1.6}
       and 1.6 not in spans.get(pc.VIA_BLIND, set()),
       str(spans))

resultats_micro = analyser_micro.analyse(*[sorted_vias(micro)[0], sorted_vias(micro)[-1]])
principal = max([r for r in resultats_micro["records"] if r["kind"] == "track"],
                key=lambda r: r["length_mm"])
verify("R15", "Z0 du resume = Z0 du segment principal",
       abs(resultats_micro["impedance_ohm"] - principal["geometry"]["z0"]) < 1e-9,
       "%.2f Ohm" % resultats_micro["impedance_ohm"])

ok, message = pc.ConfigManager().save()
verify("R11", "save() retourne (succes, message) sans lever",
       isinstance(ok, bool), "ok=%s" % ok)

config_casse = os.path.join(HERE, "_config_casse.json")
with open(config_casse, "w") as handle:
    handle.write('{"copper_oz": 0, "ground_net_names": "GND", "freq_mhz": "x"}')
sauvegarde = pc.CONFIG_FILE
pc.CONFIG_FILE = config_casse
casse = pc.ConfigManager()
calc_casse = pc.ParasiticCalculator(casse)
verify("R19", "Configuration corrompue normalisee sans planter",
       casse.get("copper_oz") > 0
       and isinstance(casse.get("ground_net_names"), list)
       and calc_casse.resistance(10e-3, 0.3e-3) > 0,
       "copper_oz=%.2f" % casse.get("copper_oz"))
pc.CONFIG_FILE = sauvegarde
os.remove(config_casse)

verify("R20", "Garde sur pcbnew.GetBoard() is None",
       "if board is None" in source, "")

morts = [nom for nom in ("EPSILON_R_FR4", "via_wall_thickness_um",
                         "show_intermediate_vias") if nom in source]
verify("R22", "Reglages fantomes et constantes mortes supprimes",
       len(morts) == 0, str(morts))

verify("R25", "Retard de propagation nomme correctement",
       "Retard de propagation" in source and "sqrt(l * c)" not in source, "")

print()
print("=" * 100)
en_echec = [r for r in resultats if r[2] != "CORRIGE"]
print("%d verifications, %d correctes, %d en echec"
      % (len(resultats), len(resultats) - len(en_echec), len(en_echec)))
for echec in en_echec:
    print("  ECHEC :", echec)
sys.exit(1 if en_echec else 0)
