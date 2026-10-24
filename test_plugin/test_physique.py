#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Confronte les formules du plugin a des valeurs de reference publiees.

Executer avec le Python de KiCad (module pcbnew requis) :

    python3 test_physique.py
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

import parasitic_calculator as pc

echecs = []


def check(label, obtained, reference, tolerance_pct, unit=""):
    if reference == 0:
        ecart = abs(obtained)
        ok = ecart < tolerance_pct
    else:
        ecart = abs(obtained - reference) / abs(reference) * 100.0
        ok = ecart <= tolerance_pct
    print("  %-48s %11.4f %-4s (ref %9.4f)  ecart %6.2f%%  %s" % (
        label, obtained, unit, reference, ecart, "OK" if ok else "ECHEC"))
    if not ok:
        echecs.append((label, obtained, reference, ecart))


config = pc.ConfigManager()
config.set("temp_c", 20.0)
config.set("er_fr4", 4.5)
config.set("copper_oz", 1.0)
config.set("freq_mhz", 100.0)
calc = pc.ParasiticCalculator(config)

print("=" * 92)
print("FORMULES CONTRE VALEURS DE REFERENCE")
print("=" * 92)

check("Microstrip w=3 mm h=1.6 mm er=4.5 -> Z0",
      calc.z0_microstrip(3e-3, 1.6e-3), 50.0, 2.0, "Ohm")

check("Stripline w=0.716 mm b=1.6 mm er=4.5 -> Z0",
      calc.z0_stripline(0.716e-3, 1.6e-3), 50.0, 2.0, "Ohm")

check("Stripline symetrique == asymetrique (h/2, h/2)",
      calc.stripline_asym(0.3e-3, 0.8e-3, 0.8e-3),
      calc.z0_stripline(0.3e-3, 1.6e-3), 0.5, "Ohm")

check("Epaisseur de peau du cuivre a 100 MHz",
      calc.skin_depth() * 1e6, 6.6, 5.0, "um")

config.set("freq_mhz", 1.0)
calc = pc.ParasiticCalculator(config)
check("Epaisseur de peau du cuivre a 1 MHz",
      calc.skin_depth() * 1e6, 66.0, 5.0, "um")

config.set("freq_mhz", 100.0)
calc = pc.ParasiticCalculator(config)

check("Inductance de via h=1.27 mm d=0.254 mm",
      calc.via_inductance(0.254, 1.27) * 1e9, 1.015, 1.0, "nH")

check("Inductance piste isolee 0.3 mm sur 10 mm",
      calc.inductance_isolated(10e-3, 0.3e-3) * 1e9, 10.6, 15.0, "nH")

print()
print("  Coherence des lignes de transmission (Z0 = sqrt(L/C), L*C = eps*(l/c)^2) :")

lines = {
    "microstrip": (calc.z0_microstrip(0.3e-3, 1.53e-3),
                   calc.eps_eff_microstrip(0.3e-3, 1.53e-3)),
    "stripline": (calc.z0_stripline(0.3e-3, 0.974e-3), calc.er),
    "cpw": (calc.z0_cpw(0.3e-3, 0.2e-3), calc.eps_eff_cpw(0.3e-3, 0.2e-3)),
    "cpwg": (calc.z0_cpw(0.3e-3, 0.2e-3, 0.487e-3),
             calc.eps_eff_cpw(0.3e-3, 0.2e-3, 0.487e-3)),
}
for name, (z0, eps_eff) in lines.items():
    length = 0.02
    inductance, capacitance = calc.lc_from_z0(z0, eps_eff, length)
    check("L*C = eps*(l/c)^2 [%s]" % name,
          inductance * capacitance / (eps_eff * (length / pc.C_LUMIERE) ** 2),
          1.0, 0.01)
    check("sqrt(L/C) = Z0 [%s]" % name,
          (inductance / capacitance) ** 0.5, z0, 0.01, "Ohm")

check("K(k)/K'(k) pour k = 1/sqrt(2)", pc.k_over_kp(1.0 / 2 ** 0.5), 1.0, 0.01)

print()
print("=" * 92)
if echecs:
    print("ECHECS :", len(echecs))
    for echec in echecs:
        print("  -", echec)
    sys.exit(1)
print("FORMULES CONFORMES AUX REFERENCES")
