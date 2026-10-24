#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
KiCad Plugin : Calculateur avance de parasites R, L, C des pistes PCB
Version 1.1.0 - Modeles de ligne de transmission multiples + vias traversants,
borgnes, enterres et microvias.
Compatible KiCad 7.x / 8.x / 9.x / 10.x

Chaine de calcul (voir l'onglet "Modeles" de la fenetre de resultats) :

  Resistance DC          R = rho(T) * l / (w * t)
  Resistance AC          R = rho(T) * l / (2*(w+t) * delta), delta = sqrt(2*rho/(omega*mu0))
  Piste isolee           L = (mu0*l/2pi) * [ln(2l/(w+t)) + 0.5 + (w+t)/(3l)]      (Grover)
  Microstrip             Z0, eps_eff (Hammerstad-Jensen), puis L' = Z0*sqrt(eps_eff)/c
                                                          C' = sqrt(eps_eff)/(Z0*c)
  Stripline symetrique   Z0 = (30*pi/sqrt(er)) / (Weff/b + 0.4413)                (Steer/Wheeler)
  Stripline asymetrique  methode des deux capacites (Steer)
  CPW                    Z0 = (30*pi/sqrt(eps_eff)) * K(k')/K(k)                 (Wen)
  CPWG                   Z0 = (30*pi/sqrt(eps_eff)) * K(k')/K(k)                  (Ghione-Naldi)
  Via                    R = rho(T)*h/(pi*(R^2-r^2))
                         L = (mu0*h/2pi) * [ln(4h/d) + 1]                        (Johnson & Graham)
                         C = 1.41e-12/0.0254 * er * h * D1 / (D2 - D1)          (Johnson & Graham)

Sources : voir la constante SOURCES et l'onglet "Modeles".
"""

import pcbnew
import wx
import math
import os
import json
from collections import deque

# ---------------------------------------------------------------------------
# Constantes physiques (SI sauf mention contraire)
# ---------------------------------------------------------------------------
RHO_CUIVRE_20C = 1.68e-8      # Ohm.m, resistivite du cuivre a 20 degres C
TEMP_COEF_CUIVRE = 0.00393    # 1/degre C
MU_0 = 4e-7 * math.pi         # H/m
EPSILON_0 = 8.8541878128e-12  # F/m
C_LUMIERE = 299792458.0       # m/s
MM_CUIVRE_PAR_OZ = 0.035      # 35 um par once de cuivre

SOURCES = [
    ("Microstrip (Z0, eps_eff)", "Hammerstad-Jensen",
     "https://en.wikipedia.org/wiki/Microstrip"),
    ("Microstrip (Z0, pertes)", "Microwaves101",
     "https://www.microwaves101.com/encyclopedias/microstrip"),
    ("L' et C' d'une ligne (L'=Z0*sqrt(eps)/c)", "Qucs - Single microstrip line",
     "https://qucs.sourceforge.net/tech/node75.html"),
    ("Stripline (Z0, asymetrique)", "Wikipedia / M. Steer, Engineering LibreTexts",
     "https://en.wikipedia.org/wiki/Stripline"),
    ("Stripline (geometrie)", "Microwaves101",
     "https://www.microwaves101.com/encyclopedias/stripline"),
    ("CPW / CPWG (Ghione-Naldi)", "everything RF - Coplanar Waveguide Calculator",
     "https://www.everythingrf.com/rf-calculators/coplanar-waveguide-calculator"),
    ("Effet de peau (delta)", "Wikipedia - Skin effect",
     "https://en.wikipedia.org/wiki/Skin_effect"),
    ("Resistivite du cuivre (rho20, alpha)", "Wikipedia - Electrical resistivity",
     "https://en.wikipedia.org/wiki/Electrical_resistivity_and_conductivity"),
    ("Inductance piste isolee (Grover)", "Grover, Inductance Calculations (NIST Bull. 169)",
     "https://nvlpubs.nist.gov/nistpubs/bulletin/08/nbsbulletinv8n1p1_A2b.pdf"),
    ("Inductance de via", "Johnson & Graham, High-Speed Digital Design",
     "https://www.protoexpress.com/blog/how-via-impedance-impacts-signal-integrity-in-pcbs"),
    ("Relation ligne de transmission", "Wikipedia - Transmission line",
     "https://en.wikipedia.org/wiki/Transmission_line"),
]

# ---------------------------------------------------------------------------
# Compatibilite KiCad 7 / 8 / 9 / 10
# ---------------------------------------------------------------------------
IU_PER_MM = float(getattr(pcbnew, "PCB_IU_PER_MM", 0) or getattr(pcbnew, "IU_PER_MM", 1e6))


def layer_name(layer_id):
    """Nom de couche, quelle que soit la version de KiCad."""
    fn = getattr(pcbnew, "LayerName", None)
    if fn is not None:
        try:
            return fn(layer_id)
        except Exception:
            pass
    try:
        return pcbnew.Board.GetStandardLayerName(layer_id)
    except Exception:
        return str(layer_id)


def to_mm(value):
    """Convertit une valeur IU (entier) ou un VECTOR2I en mm.

    Un objet portant .x et .y donne un tuple (x_mm, y_mm), un entier donne un float.
    """
    if hasattr(value, "x") and hasattr(value, "y"):
        return (value.x / IU_PER_MM, value.y / IU_PER_MM)
    return value / IU_PER_MM


def is_copper(layer_id):
    fn = getattr(pcbnew, "IsCopperLayer", None)
    if fn is not None:
        try:
            return bool(fn(layer_id))
        except Exception:
            pass
    return 0 <= layer_id < 32


def copper_stack(board):
    """Liste ordonnee des couches cuivre actives (F.Cu -> B.Cu)."""
    try:
        stack = [lid for lid in board.GetEnabledLayers().CuStack()]
        if stack:
            return stack
    except Exception:
        pass
    out = []
    start = int(getattr(pcbnew, "PCBNEW_LAYER_ID_START", 0))
    for lid in range(start, start + 64):
        try:
            if board.IsLayerEnabled(lid) and is_copper(lid):
                out.append(lid)
        except Exception:
            continue
    return out


def agm(a, b, iterations=32):
    """Moyenne arithmetique-geometrique (convergence quadratique)."""
    for _ in range(iterations):
        a, b = 0.5 * (a + b), math.sqrt(a * b)
    return a


def k_over_kp(k):
    """Rapport K(k)/K'(k) des integrales elliptiques completes, par AGM.

    K(k) = pi / (2 * AGM(1, k'))  avec k' = sqrt(1 - k^2)
    donc K(k)/K'(k) = AGM(1, k) / AGM(1, k')
    """
    if not (0.0 < k < 1.0):
        return None
    kp = math.sqrt(1.0 - k * k)
    return agm(1.0, k) / agm(1.0, kp)


# ---------------------------------------------------------------------------
# Modeles de ligne
# ---------------------------------------------------------------------------
MODEL_ISOLATED = "piste isolee"
MODEL_MICROSTRIP = "microstrip"
MODEL_STRIPLINE = "stripline symetrique"
MODEL_STRIPLINE_ASYM = "stripline asymetrique"
MODEL_CPW = "coplanaire (CPW)"
MODEL_CPWG = "coplanaire avec plan arriere (CPWG)"

VIA_THROUGH = "traversant"
VIA_BLIND = "borgne"
VIA_BURIED = "enterre"
VIA_MICROVIA = "microvia"


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
def _config_path():
    here = os.path.dirname(os.path.abspath(__file__))
    candidate = os.path.join(here, "parasitic_config.json")
    if os.access(here, os.W_OK) or os.path.exists(candidate):
        return candidate
    try:
        base = wx.StandardPaths.Get().GetUserConfigDir()
        folder = os.path.join(base, "kicad-parasitic-calculator")
        if not os.path.isdir(folder):
            os.makedirs(folder)
        return os.path.join(folder, "parasitic_config.json")
    except Exception:
        return candidate


CONFIG_FILE = _config_path()


class ConfigManager:
    """Gestionnaire de configuration persistante (JSON)."""

    DEFAULTS = {
        "copper_oz": 1.0,
        "temp_c": 25.0,
        "er_fr4": 4.5,
        "freq_mhz": 100.0,
        "include_ac_resistance": True,
        "detect_reference_planes": True,
        "ground_net_names": ["GND", "VSS", "0", "GROUND", "AGND", "DGND"],
        "cpw_gap_mm": 0.0,
        "antipad_clearance_mm": 0.25,
        "default_dielectric_mm": 0.2,
    }

    def __init__(self):
        self.config = {}
        self.warning = None
        self.load()

    def load(self):
        self.config = {}
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r") as handle:
                    data = json.load(handle)
                if isinstance(data, dict):
                    self.config = data
            except (OSError, ValueError) as exc:
                self.warning = "Configuration illisible (%s), valeurs par defaut utilisees." % exc
                self.config = {}
        for key, value in self.DEFAULTS.items():
            if key not in self.config:
                self.config[key] = value
        self._normalise()

    def _normalise(self):
        """Force les types attendus : une config corrompue ne doit pas planter le calcul."""
        for key in ("copper_oz", "temp_c", "er_fr4", "freq_mhz",
                    "cpw_gap_mm", "antipad_clearance_mm", "default_dielectric_mm"):
            try:
                self.config[key] = float(self.config[key])
            except (TypeError, ValueError):
                self.config[key] = float(self.DEFAULTS[key])
        if self.config["copper_oz"] <= 0:
            self.config["copper_oz"] = self.DEFAULTS["copper_oz"]
        if self.config["er_fr4"] < 1.0:
            self.config["er_fr4"] = self.DEFAULTS["er_fr4"]
        if self.config["default_dielectric_mm"] <= 0:
            self.config["default_dielectric_mm"] = self.DEFAULTS["default_dielectric_mm"]
        for key in ("include_ac_resistance", "detect_reference_planes"):
            self.config[key] = bool(self.config[key])
        names = self.config.get("ground_net_names")
        if isinstance(names, str):
            names = [n.strip() for n in names.split(",")]
        if not isinstance(names, (list, tuple)):
            names = list(self.DEFAULTS["ground_net_names"])
        self.config["ground_net_names"] = [str(n).strip() for n in names if str(n).strip()]

    def save(self):
        """Ecrit la configuration. Retourne (succes, message)."""
        try:
            with open(CONFIG_FILE, "w") as handle:
                json.dump(self.config, handle, indent=2)
            return True, None
        except OSError as exc:
            return False, "Impossible d'ecrire %s :\n%s" % (CONFIG_FILE, exc)

    def get(self, key):
        return self.config.get(key, self.DEFAULTS.get(key))

    def set(self, key, value):
        self.config[key] = value


# ---------------------------------------------------------------------------
# Empilement des couches
# ---------------------------------------------------------------------------
class Stackup:
    """Empilement physique deduit du nombre de couches et de l'epaisseur carte.

    Pour n couches cuivre d'epaisseur t_cu dans une carte d'epaisseur t_total,
    il y a (n-1) lames de dielectrique :

        h = (t_total - n * t_cu) / (n - 1)

    et la distance entre les plans medians de deux couches adjacentes vaut :

        pas = t_cu + h = (t_total - t_cu) / (n - 1)
    """

    def __init__(self, board, copper_thickness_mm):
        self.layers = copper_stack(board)
        self.index = {lid: i for i, lid in enumerate(self.layers)}
        self.t_cu = float(copper_thickness_mm)
        settings = board.GetDesignSettings()
        self.t_total = to_mm(settings.GetBoardThickness())
        n = len(self.layers)
        if n >= 2:
            self.h = (self.t_total - n * self.t_cu) / (n - 1)
            self.pitch = (self.t_total - self.t_cu) / (n - 1)
        else:
            self.h = self.t_total
            self.pitch = self.t_total
        if self.h <= 0:
            self.h = self.t_total / max(n, 1)
            self.pitch = self.h + self.t_cu
        self.n = n

    def is_outer(self, layer_id):
        if layer_id not in self.index:
            return False
        i = self.index[layer_id]
        return i == 0 or i == self.n - 1

    def distance(self, layer_a, layer_b):
        """Distance entre les plans medians de deux couches cuivre (mm)."""
        if layer_a not in self.index or layer_b not in self.index:
            return self.h
        return abs(self.index[layer_a] - self.index[layer_b]) * self.pitch

    def dielectric(self, layer_a, layer_b):
        """Epaisseur de dielectrique separant deux couches cuivre (mm).

        C'est la hauteur h utilisee par les modeles de ligne : pour un microstrip
        la distance piste-plan vaut h, pour une stripline la hauteur totale entre
        les deux plans vaut 2*h (une lame de chaque cote de la piste).
        """
        if layer_a not in self.index or layer_b not in self.index:
            return self.h
        return abs(self.index[layer_a] - self.index[layer_b]) * self.h

    def span_length(self, layer_top, layer_bottom):
        """Longueur du fut d'un via entre deux couches (mm), faces externes comprises."""
        return self.distance(layer_top, layer_bottom) + self.t_cu


# ---------------------------------------------------------------------------
# Detection des plans de reference
# ---------------------------------------------------------------------------
class BoardModel:
    """Zones de cuivre, nets de masse et plans de reference par couche."""

    def __init__(self, board, config):
        self.board = board
        self.config = config
        self.ground_nets = self._find_ground_nets()
        self.zones = self._extract_zones()

    def _find_ground_nets(self):
        """Codes des nets de masse : egalite exacte du nom, insensible a la casse."""
        names = {str(n).strip().lower() for n in self.config.get("ground_net_names") if str(n).strip()}
        codes = set()
        if not names:
            return codes
        try:
            for net in self.board.GetNetsByName().values():
                net_name = str(net.GetNetname()).strip().lower()
                if net_name and net_name in names:
                    codes.add(net.GetNetCode())
        except Exception:
            pass
        return codes

    def _extract_zones(self):
        zones = []
        try:
            iterator = self.board.Zones()
        except Exception:
            return zones
        for zone in iterator:
            try:
                layers = [lid for lid in zone.GetLayerSet().Seq() if is_copper(lid)]
            except Exception:
                try:
                    layers = [zone.GetLayer()]
                except Exception:
                    continue
            try:
                net = zone.GetNetCode()
            except Exception:
                net = 0
            try:
                bbox = zone.GetBoundingBox()
            except Exception:
                bbox = None
            for layer in layers:
                zones.append({"layer": layer, "net": net, "bbox": bbox})
        return zones

    def zones_on(self, layer_id, position=None):
        out = []
        for zone in self.zones:
            if zone["layer"] != layer_id:
                continue
            bbox = zone["bbox"]
            if position is not None and bbox is not None:
                try:
                    if not bbox.Contains(position):
                        continue
                except Exception:
                    pass
            out.append(zone)
        return out

    def has_plane(self, layer_id, position=None):
        return len(self.zones_on(layer_id, position)) > 0

    def has_ground_plane(self, layer_id, position=None):
        return any(z["net"] in self.ground_nets for z in self.zones_on(layer_id, position))

    def nearest_planes(self, layer_id, stackup, position=None):
        """Couches de cuivre encadrant layer_id qui portent un plan (mm de distance).

        Retourne (couche_haute, couche_basse) ; None si aucune.
        """
        if layer_id not in stackup.index:
            return None, None
        i = stackup.index[layer_id]
        above = below = None
        for j in range(i - 1, -1, -1):
            candidate = stackup.layers[j]
            if self.has_plane(candidate, position):
                above = candidate
                break
        for j in range(i + 1, stackup.n):
            candidate = stackup.layers[j]
            if self.has_plane(candidate, position):
                below = candidate
                break
        return above, below


# ---------------------------------------------------------------------------
# Moteur de calcul
# ---------------------------------------------------------------------------
class ParasiticCalculator:
    """Moteur de calcul pur : entrees SI (metres, Hz), sorties SI (H, F, Ohm)."""

    def __init__(self, config):
        self.config = config
        self.temp_c = float(config.get("temp_c"))
        self.thickness_m = float(config.get("copper_oz")) * MM_CUIVRE_PAR_OZ * 1e-3
        self.freq_hz = float(config.get("freq_mhz")) * 1e6
        self.er = float(config.get("er_fr4"))
        self.rho = RHO_CUIVRE_20C * (1.0 + TEMP_COEF_CUIVRE * (self.temp_c - 20.0))

    # -- resistance --------------------------------------------------------
    def resistance(self, length_m, width_m):
        """R = rho(T) * l / (w * t)."""
        section = width_m * self.thickness_m
        if length_m <= 0 or width_m <= 0 or section <= 0:
            return 0.0
        return self.rho * length_m / section

    def skin_depth(self):
        """delta = sqrt(2 * rho / (omega * mu0))."""
        if self.freq_hz <= 0 or self.rho <= 0:
            return float("inf")
        omega = 2.0 * math.pi * self.freq_hz
        return math.sqrt(2.0 * self.rho / (omega * MU_0))

    def resistance_ac(self, length_m, width_m):
        """R_AC : section effective = perimetre * delta des que t >= 2*delta."""
        r_dc = self.resistance(length_m, width_m)
        if not self.config.get("include_ac_resistance") or self.freq_hz <= 0 or r_dc <= 0:
            return r_dc
        delta = self.skin_depth()
        if not math.isfinite(delta) or self.thickness_m < 2.0 * delta:
            return r_dc
        perimeter = 2.0 * (width_m + self.thickness_m)
        section_eff = perimeter * delta
        if section_eff <= 0:
            return r_dc
        return max(r_dc, self.rho * length_m / section_eff)

    # -- microstrip (Hammerstad-Jensen) ------------------------------------
    def eps_eff_microstrip(self, width_m, height_m):
        u = width_m / height_m
        base = 1.0 / math.sqrt(1.0 + 12.0 / u)
        if u < 1.0:
            base += 0.04 * (1.0 - u) ** 2
        return (self.er + 1.0) / 2.0 + (self.er - 1.0) / 2.0 * base

    def z0_microstrip(self, width_m, height_m):
        u = width_m / height_m
        eps_eff = self.eps_eff_microstrip(width_m, height_m)
        if u < 1.0:
            shape = math.log(8.0 / u + 0.25 * u)
            return 60.0 / math.sqrt(eps_eff) * shape
        shape = u + 1.393 + 0.667 * math.log(u + 1.444)
        return 120.0 * math.pi / (math.sqrt(eps_eff) * shape)

    # -- stripline (Steer / Wheeler) ---------------------------------------
    def z0_stripline(self, width_m, gap_m, thickness_m=None):
        """Stripline symetrique centree : gap_m = distance totale entre les deux plans."""
        t = self.thickness_m if thickness_m is None else thickness_m
        w = width_m / gap_m
        big_t = t / gap_m
        if w < 0.35:
            w_eff = w - (0.35 - w) ** 2 / (1.0 + 12.0 * big_t)
        else:
            w_eff = w
        denominator = w_eff + 0.4413
        if denominator <= 0:
            return 0.0
        return 30.0 * math.pi / math.sqrt(self.er) / denominator

    def stripline_asym(self, width_m, height_upper_m, height_lower_m):
        """Stripline asymetrique : methode des deux capacites (Steer).

        Chaque demi-structure est traitee comme une stripline centree de hauteur 2h.
        """
        z_upper = self.z0_stripline(width_m, 2.0 * height_upper_m)
        z_lower = self.z0_stripline(width_m, 2.0 * height_lower_m)
        if z_upper <= 0 or z_lower <= 0:
            return 0.0
        c_upper = math.sqrt(self.er) / (C_LUMIERE * z_upper)
        c_lower = math.sqrt(self.er) / (C_LUMIERE * z_lower)
        c_total = c_upper / 2.0 + c_lower / 2.0
        if c_total <= 0:
            return 0.0
        l_total = self.er / (c_total * C_LUMIERE ** 2)
        return math.sqrt(l_total / c_total)

    # -- coplanaire (Wen / Ghione-Naldi) -----------------------------------
    def _cpw_modulus(self, width_m, gap_m):
        a = width_m / 2.0
        b = a + gap_m
        if a <= 0 or b <= 0:
            return None
        return a / b

    def eps_eff_cpw(self, width_m, gap_m, height_m=None):
        if height_m is None or height_m <= 0:
            return (self.er + 1.0) / 2.0
        k = self._cpw_modulus(width_m, gap_m)
        if k is None:
            return (self.er + 1.0) / 2.0
        ratio = k_over_kp(k)
        if not ratio:
            return (self.er + 1.0) / 2.0
        a = width_m / 2.0
        b = a + gap_m
        k3 = math.tanh(math.pi * a / (2.0 * height_m)) / math.tanh(math.pi * b / (2.0 * height_m))
        ratio3 = k_over_kp(k3)
        if not ratio3:
            return (self.er + 1.0) / 2.0
        product = ratio * ratio3
        return (1.0 + self.er * product) / (1.0 + product)

    def z0_cpw(self, width_m, gap_m, height_m=None):
        k = self._cpw_modulus(width_m, gap_m)
        if k is None:
            return 0.0
        ratio = k_over_kp(k)
        if not ratio:
            return 0.0
        eps_eff = self.eps_eff_cpw(width_m, gap_m, height_m)
        return 30.0 * math.pi / (math.sqrt(eps_eff) * ratio)

    # -- piste isolee (Grover) ---------------------------------------------
    def inductance_isolated(self, length_m, width_m):
        """L = (mu0*l/2pi) * [ln(2l/(w+t)) + 0.5 + (w+t)/(3l)]."""
        section = width_m + self.thickness_m
        if length_m <= 0 or section <= 0:
            return 0.0
        ratio = 2.0 * length_m / section
        if ratio <= 0:
            return 0.0
        factor = math.log(ratio) + 0.5 + section / (3.0 * length_m)
        return MU_0 * length_m / (2.0 * math.pi) * factor

    # -- conversion ligne de transmission ----------------------------------
    def lc_from_z0(self, z0, eps_eff, length_m):
        """L' = Z0*sqrt(eps_eff)/c et C' = sqrt(eps_eff)/(Z0*c).

        Garantit Z0 = sqrt(L/C) et L*C = eps_eff*(l/c)^2 pour la meme ligne.
        """
        if z0 <= 0 or eps_eff <= 0 or length_m <= 0:
            return 0.0, 0.0
        root = math.sqrt(eps_eff)
        inductance = z0 * root / C_LUMIERE * length_m
        capacitance = root / (z0 * C_LUMIERE) * length_m
        return inductance, capacitance

    def propagation_delay(self, eps_eff, length_m):
        """T_d = l * sqrt(eps_eff) / c."""
        if eps_eff <= 0 or length_m <= 0:
            return 0.0
        return length_m * math.sqrt(eps_eff) / C_LUMIERE

    # -- vias --------------------------------------------------------------
    def via_resistance(self, pad_diameter_mm, drill_mm, span_mm):
        """R = rho(T) * h / (pi * (R^2 - r^2)) pour un fut cylindrique creux."""
        outer = pad_diameter_mm / 2.0 * 1e-3
        inner = drill_mm / 2.0 * 1e-3
        height = span_mm * 1e-3
        if outer <= inner or height <= 0:
            return 0.0
        section = math.pi * (outer ** 2 - inner ** 2)
        if section <= 0:
            return 0.0
        return self.rho * height / section

    def via_inductance(self, drill_mm, span_mm):
        """L = (mu0*h/2pi) * [ln(4h/d) + 1] (Johnson & Graham)."""
        radius = drill_mm / 2.0 * 1e-3
        height = span_mm * 1e-3
        if radius <= 0 or height <= 0:
            return 0.0
        ratio = 4.0 * height / (2.0 * radius)
        if ratio <= 0:
            return 0.0
        return MU_0 * height / (2.0 * math.pi) * (math.log(ratio) + 1.0)

    def via_capacitance(self, pad_diameter_mm, antipad_mm, span_mm):
        """C = (1.41e-12/0.0254) * er * h * D1 / (D2 - D1) (Johnson & Graham)."""
        d1 = pad_diameter_mm * 1e-3
        d2 = antipad_mm * 1e-3
        height = span_mm * 1e-3
        if d1 <= 0 or height <= 0 or d2 <= d1:
            return 0.0
        return 1.41e-12 / 0.0254 * self.er * height * d1 / (d2 - d1)


# ---------------------------------------------------------------------------
# Analyse du chemin entre deux vias
# ---------------------------------------------------------------------------
TOLERANCE_IU = 1000  # 1 um


def item_points(item):
    """Points d'accroche d'une piste ou d'un via (en IU)."""
    if isinstance(item, pcbnew.PCB_VIA):
        return [item.GetPosition()]
    return [item.GetStart(), item.GetEnd()]


def item_layers(item):
    """Ensemble des couches cuivre occupees par l'element."""
    if isinstance(item, pcbnew.PCB_VIA):
        try:
            return {lid for lid in item.GetLayerSet().Seq() if is_copper(lid)}
        except Exception:
            return set()
    try:
        return {item.GetLayer()}
    except Exception:
        return set()


def item_length_mm(item):
    """Longueur d'un element de piste en mm (arcs compris)."""
    try:
        return item.GetLength() / IU_PER_MM
    except Exception:
        start = to_mm(item.GetStart())
        end = to_mm(item.GetEnd())
        return math.hypot(end[0] - start[0], end[1] - start[1])


class PathAnalyser:
    """Construit le chemin entre deux vias et agrege les parasites."""

    def __init__(self, board, config):
        self.board = board
        self.config = config
        self.calc = ParasiticCalculator(config)
        thickness_mm = float(config.get("copper_oz")) * MM_CUIVRE_PAR_OZ
        self.stackup = Stackup(board, thickness_mm)
        self.model = BoardModel(board, config)
        self.cpw_gap_mm = self._resolve_gap()

    def _resolve_gap(self):
        """Ecart coplanaire : valeur configuree, sinon clearance du netclass, sinon 0.2 mm."""
        configured = float(self.config.get("cpw_gap_mm") or 0.0)
        if configured > 0:
            return configured
        try:
            netclass = self.board.GetDesignSettings().GetDefault()
            clearance = to_mm(netclass.GetClearance())
            if clearance > 0:
                return clearance
        except Exception:
            pass
        return 0.2

    # -- graphe ------------------------------------------------------------
    def _build_index(self, items):
        index = {}
        for item in items:
            for position in item_points(item):
                index.setdefault((position.x, position.y), []).append(item)
        return index

    def _neighbours(self, point, index):
        found = []
        tolerance = TOLERANCE_IU
        for dx in (-tolerance, 0, tolerance):
            for dy in (-tolerance, 0, tolerance):
                found.extend(index.get((point.x + dx, point.y + dy), []))
        return found

    def find_path(self, start_via, end_via):
        """Plus court chemin en nombre d'elements, via BFS, couches compatibles."""
        net_code = start_via.GetNetCode()
        items = [t for t in self.board.GetTracks() if t.GetNetCode() == net_code]
        if not any(t is start_via for t in items):
            items.append(start_via)
        if not any(t is end_via for t in items):
            items.append(end_via)

        index = self._build_index(items)
        layers = {id(it): item_layers(it) for it in items}
        points = {id(it): item_points(it) for it in items}

        queue = deque([start_via])
        previous = {id(start_via): None}
        seen = {id(start_via)}

        while queue:
            current = queue.popleft()
            if current is end_via:
                break
            for point in points[id(current)]:
                for candidate in self._neighbours(point, index):
                    key = id(candidate)
                    if key in seen:
                        continue
                    if not layers[id(current)].intersection(layers[key]):
                        continue
                    seen.add(key)
                    previous[key] = current
                    queue.append(candidate)

        if id(end_via) not in seen:
            return []
        path = []
        node = end_via
        while node is not None:
            path.append(node)
            node = previous[id(node)]
        path.reverse()
        return path

    # -- choix du modele ---------------------------------------------------
    def select_model(self, layer_id, position, width_mm):
        """Determine le modele de ligne et ses parametres geometriques."""
        info = {
            "model": MODEL_ISOLATED,
            "width_mm": width_mm,
            "height_mm": None,
            "height_upper_mm": None,
            "height_lower_mm": None,
            "gap_mm": None,
            "eps_eff": None,
            "z0": 0.0,
        }
        if not self.config.get("detect_reference_planes"):
            height = float(self.config.get("default_dielectric_mm"))
            info.update(model=MODEL_MICROSTRIP, height_mm=height)
            info["eps_eff"] = self.calc.eps_eff_microstrip(width_mm * 1e-3, height * 1e-3)
            info["z0"] = self.calc.z0_microstrip(width_mm * 1e-3, height * 1e-3)
            return info

        above, below = self.model.nearest_planes(layer_id, self.stackup, position)
        height_above = self.stackup.dielectric(layer_id, above) if above is not None else None
        height_below = self.stackup.dielectric(layer_id, below) if below is not None else None
        coplanar = self.model.has_plane(layer_id, position)

        width_m = width_mm * 1e-3

        if height_above and height_below and not self.stackup.is_outer(layer_id):
            total = height_above + height_below
            if abs(height_above - height_below) < 1e-6:
                info.update(model=MODEL_STRIPLINE, height_mm=total)
                info["eps_eff"] = self.calc.er
                info["z0"] = self.calc.z0_stripline(width_m, total * 1e-3)
            else:
                info.update(model=MODEL_STRIPLINE_ASYM,
                            height_upper_mm=height_above,
                            height_lower_mm=height_below,
                            height_mm=total)
                info["eps_eff"] = self.calc.er
                info["z0"] = self.calc.stripline_asym(width_m,
                                                      height_above * 1e-3,
                                                      height_below * 1e-3)
            return info

        reference = height_below or height_above
        if coplanar and reference:
            info.update(model=MODEL_CPWG, height_mm=reference, gap_mm=self.cpw_gap_mm)
            info["eps_eff"] = self.calc.eps_eff_cpw(width_m, self.cpw_gap_mm * 1e-3,
                                                    reference * 1e-3)
            info["z0"] = self.calc.z0_cpw(width_m, self.cpw_gap_mm * 1e-3,
                                          reference * 1e-3)
            return info

        if coplanar:
            info.update(model=MODEL_CPW, gap_mm=self.cpw_gap_mm)
            info["eps_eff"] = self.calc.eps_eff_cpw(width_m, self.cpw_gap_mm * 1e-3)
            info["z0"] = self.calc.z0_cpw(width_m, self.cpw_gap_mm * 1e-3)
            return info

        if reference:
            info.update(model=MODEL_MICROSTRIP, height_mm=reference)
            info["eps_eff"] = self.calc.eps_eff_microstrip(width_m, reference * 1e-3)
            info["z0"] = self.calc.z0_microstrip(width_m, reference * 1e-3)
            return info

        return info

    # -- elements ----------------------------------------------------------
    def track_record(self, track):
        """Parasites d'un segment de piste."""
        length_mm = item_length_mm(track)
        width_mm = to_mm(track.GetWidth())
        layer_id = track.GetLayer()
        position = track.GetStart()
        geometry = self.select_model(layer_id, position, width_mm)

        length_m = length_mm * 1e-3
        width_m = width_mm * 1e-3
        r_dc = self.calc.resistance(length_m, width_m)
        r_ac = self.calc.resistance_ac(length_m, width_m)

        if geometry["model"] == MODEL_ISOLATED:
            inductance = self.calc.inductance_isolated(length_m, width_m)
            capacitance = 0.0
            delay = 0.0
        else:
            inductance, capacitance = self.calc.lc_from_z0(
                geometry["z0"], geometry["eps_eff"] or 1.0, length_m)
            delay = self.calc.propagation_delay(geometry["eps_eff"] or 1.0, length_m)

        return {
            "kind": "track",
            "layer": layer_name(layer_id),
            "length_mm": length_mm,
            "width_mm": width_mm,
            "geometry": geometry,
            "r_dc": r_dc,
            "r_ac": r_ac,
            "l": inductance,
            "c": capacitance,
            "delay": delay,
            "start": to_mm(track.GetStart()),
            "end": to_mm(track.GetEnd()),
        }

    def via_kind(self, via):
        """Classe le via : traversant, borgne, enterre ou microvia."""
        try:
            top = via.TopLayer()
            bottom = via.BottomLayer()
        except Exception:
            return VIA_THROUGH, None, None

        for predicate, label in (("IsMicroVia", VIA_MICROVIA),
                                 ("IsBuriedVia", VIA_BURIED),
                                 ("IsBlindVia", VIA_BLIND)):
            check = getattr(via, predicate, None)
            if check is None:
                continue
            try:
                if check():
                    return label, top, bottom
            except Exception:
                continue

        index = self.stackup.index
        if top not in index or bottom not in index:
            return VIA_THROUGH, top, bottom
        first = self.stackup.layers[0]
        last = self.stackup.layers[-1]
        if top == first and bottom == last:
            return VIA_THROUGH, top, bottom
        if top == first or bottom == last:
            if abs(index[bottom] - index[top]) == 1:
                return VIA_MICROVIA, top, bottom
            return VIA_BLIND, top, bottom
        return VIA_BURIED, top, bottom

    def via_record(self, via):
        """Parasites d'un via, longueur reelle du fut (span)."""
        kind, top, bottom = self.via_kind(via)
        if top is not None:
            span_mm = self.stackup.span_length(top, bottom)
        else:
            span_mm = self.stackup.t_total
        pad_mm = to_mm(via.GetWidth(top if top is not None else self.stackup.layers[0]))
        drill_mm = to_mm(via.GetDrillValue())
        clearance = float(self.config.get("antipad_clearance_mm"))
        antipad_mm = pad_mm + 2.0 * clearance

        r_via = self.calc.via_resistance(pad_mm, drill_mm, span_mm)
        l_via = self.calc.via_inductance(drill_mm, span_mm)
        c_via = self.calc.via_capacitance(pad_mm, antipad_mm, span_mm)
        delay = math.sqrt(l_via * c_via) if (l_via > 0 and c_via > 0) else 0.0

        return {
            "kind": "via",
            "via_kind": kind,
            "position": to_mm(via.GetPosition()),
            "pad_mm": pad_mm,
            "drill_mm": drill_mm,
            "antipad_mm": antipad_mm,
            "span_mm": span_mm,
            "layer_top": layer_name(top) if top is not None else "?",
            "layer_bottom": layer_name(bottom) if bottom is not None else "?",
            "r_dc": r_via,
            "r_ac": r_via,
            "l": l_via,
            "c": c_via,
            "delay": delay,
        }

    # -- agregation --------------------------------------------------------
    def analyse(self, via1, via2):
        """Analyse complete entre deux vias : chemin, agregats, details."""
        path = self.find_path(via1, via2)
        if not path:
            raise ValueError(
                "Aucun chemin continu trouve entre les deux vias.\n"
                "Verifiez que les pistes sont bien connectees sur les memes couches.")

        records = []
        for item in path:
            if isinstance(item, pcbnew.PCB_VIA):
                records.append(self.via_record(item))
            else:
                records.append(self.track_record(item))

        total_r_dc = sum(r["r_dc"] for r in records)
        total_r_ac = sum(r["r_ac"] for r in records)
        total_l = sum(r["l"] for r in records)
        total_c = sum(r["c"] for r in records)
        total_delay = sum(r["delay"] for r in records)

        tracks = [r for r in records if r["kind"] == "track"]
        vias = [r for r in records if r["kind"] == "via"]

        track_length = sum(r["length_mm"] for r in tracks)
        via_length = sum(r["span_mm"] for r in vias)

        dominant = max(tracks, key=lambda r: r["length_mm"]) if tracks else None
        width_mm = dominant["width_mm"] if dominant else 0.0
        impedance = dominant["geometry"]["z0"] if dominant else 0.0

        model_counts = {}
        for record in tracks:
            name = record["geometry"]["model"]
            model_counts[name] = model_counts.get(name, 0) + 1

        via_counts = {}
        for record in vias:
            name = record["via_kind"]
            via_counts[name] = via_counts.get(name, 0) + 1

        layers = sorted({r["layer"] for r in tracks})
        layer_numbers = {lid: i for i, lid in enumerate(self.stackup.layers)}

        return {
            "length_mm": track_length + via_length,
            "track_length_mm": track_length,
            "via_length_mm": via_length,
            "width_mm": width_mm,
            "layers": len(layers),
            "layer_names": layers,
            "segments": len(records),
            "via_count": len(vias),
            "resistance_ohm": total_r_dc,
            "resistance_ac_ohm": total_r_ac,
            "inductance_h": total_l,
            "capacitance_f": total_c,
            "impedance_ohm": impedance,
            "delay_s": total_delay,
            "model_counts": model_counts,
            "via_counts": via_counts,
            "records": records,
            "stackup": {
                "layers": [layer_name(l) for l in self.stackup.layers],
                "copper_mm": self.stackup.t_cu,
                "dielectric_mm": self.stackup.h,
                "total_mm": self.stackup.t_total,
            },
            "cpw_gap_mm": self.cpw_gap_mm,
            "details": self.format_details(records, layer_numbers),
        }

    def format_details(self, records, layer_numbers):
        """Texte multi-lignes detaillant chaque element du chemin."""
        lines = []
        for index, record in enumerate(records, start=1):
            if record["kind"] == "track":
                geo = record["geometry"]
                lines.append("=== Element %d : piste [%s] - %s ===" % (
                    index, record["layer"], geo["model"].upper()))
                lines.append("  Position      : (%.3f, %.3f) -> (%.3f, %.3f) mm" % (
                    record["start"][0], record["start"][1],
                    record["end"][0], record["end"][1]))
                lines.append("  Longueur      : %.3f mm" % record["length_mm"])
                lines.append("  Largeur       : %.3f mm" % record["width_mm"])
                if geo["model"] == MODEL_STRIPLINE_ASYM:
                    lines.append("  H haut/bas    : %.3f / %.3f mm" % (
                        geo["height_upper_mm"], geo["height_lower_mm"]))
                elif geo["height_mm"] is not None:
                    lines.append("  H dielectrique: %.3f mm" % geo["height_mm"])
                if geo["gap_mm"] is not None:
                    lines.append("  Ecart coplanaire : %.3f mm" % geo["gap_mm"])
                if geo["eps_eff"] is not None:
                    lines.append("  eps_eff       : %.3f" % geo["eps_eff"])
                lines.append("  R_DC          : %sOhm" % fmt_value(record["r_dc"]))
                lines.append("  R_AC          : %sOhm" % fmt_value(record["r_ac"]))
                lines.append("  L             : %sH" % fmt_value(record["l"]))
                lines.append("  C             : %sF" % fmt_value(record["c"]))
                if geo["z0"] > 0:
                    lines.append("  Z0            : %.2f Ohm" % geo["z0"])
                if record["delay"] > 0:
                    lines.append("  Retard        : %ss" % fmt_value(record["delay"]))
                else:
                    lines.append("  Retard        : non defini (pas de plan de reference)")
            else:
                lines.append("=== Element %d : via %s @ (%.3f, %.3f) mm ===" % (
                    index, record["via_kind"].upper(),
                    record["position"][0], record["position"][1]))
                lines.append("  Couches       : %s -> %s" % (
                    record["layer_top"], record["layer_bottom"]))
                lines.append("  Longueur fut  : %.3f mm" % record["span_mm"])
                lines.append("  Pad / percage : %.3f / %.3f mm" % (
                    record["pad_mm"], record["drill_mm"]))
                lines.append("  Anti-pad      : %.3f mm" % record["antipad_mm"])
                lines.append("  R_via         : %sOhm" % fmt_value(record["r_dc"]))
                lines.append("  L_via         : %sH" % fmt_value(record["l"]))
                lines.append("  C_via         : %sF" % fmt_value(record["c"]))
            lines.append("")
        return "\n".join(lines)


def fmt_value(value):
    """Formatage compact a prefixe d'ingenierie (p, n, u, m)."""
    if value == 0:
        return "0 "
    magnitude = abs(value)
    if magnitude >= 1:
        return "%.3f " % value
    if magnitude >= 1e-3:
        return "%.3f m" % (value * 1e3)
    if magnitude >= 1e-6:
        return "%.3f u" % (value * 1e6)
    if magnitude >= 1e-9:
        return "%.3f n" % (value * 1e9)
    if magnitude >= 1e-12:
        return "%.3f p" % (value * 1e12)
    return "%.3e " % value


# ---------------------------------------------------------------------------
# Interface
# ---------------------------------------------------------------------------
class ConfigDialog(wx.Dialog):
    """Fenetre de configuration des parametres de calcul."""

    def __init__(self, parent, config_manager):
        super().__init__(parent,
                         title="Configuration du calculateur de parasites",
                         size=(470, 580))
        self.config = config_manager

        panel = wx.Panel(self)
        sizer = wx.BoxSizer(wx.VERTICAL)
        notebook = wx.Notebook(panel)

        # -- Materiaux ------------------------------------------------------
        materials = wx.Panel(notebook)
        grid = wx.FlexGridSizer(cols=2, vgap=10, hgap=15)
        grid.AddGrowableCol(1)

        self.copper_oz = wx.SpinCtrlDouble(materials, value=str(config_manager.get("copper_oz")),
                                           min=0.25, max=6.0, inc=0.25)
        grid.Add(wx.StaticText(materials, label="Cuivre (oz) :"), 0,
                 wx.ALIGN_RIGHT | wx.ALIGN_CENTER_VERTICAL)
        grid.Add(self.copper_oz, 0, wx.EXPAND)

        self.temp_c = wx.SpinCtrlDouble(materials, value=str(config_manager.get("temp_c")),
                                        min=-40, max=150, inc=1)
        grid.Add(wx.StaticText(materials, label="Temperature (degC) :"), 0,
                 wx.ALIGN_RIGHT | wx.ALIGN_CENTER_VERTICAL)
        grid.Add(self.temp_c, 0, wx.EXPAND)

        self.er_fr4 = wx.SpinCtrlDouble(materials, value=str(config_manager.get("er_fr4")),
                                        min=1.0, max=12.0, inc=0.1)
        grid.Add(wx.StaticText(materials, label="Permittivite relative :"), 0,
                 wx.ALIGN_RIGHT | wx.ALIGN_CENTER_VERTICAL)
        grid.Add(self.er_fr4, 0, wx.EXPAND)

        materials.SetSizer(grid)
        notebook.AddPage(materials, "Materiaux")

        # -- Calcul ---------------------------------------------------------
        calculation = wx.Panel(notebook)
        calc_sizer = wx.BoxSizer(wx.VERTICAL)
        calc_grid = wx.FlexGridSizer(cols=2, vgap=10, hgap=15)
        calc_grid.AddGrowableCol(1)

        self.freq_mhz = wx.SpinCtrlDouble(calculation,
                                          value=str(config_manager.get("freq_mhz")),
                                          min=0.1, max=100000, inc=1)
        calc_grid.Add(wx.StaticText(calculation, label="Frequence AC (MHz) :"), 0,
                      wx.ALIGN_RIGHT | wx.ALIGN_CENTER_VERTICAL)
        calc_grid.Add(self.freq_mhz, 0, wx.EXPAND)

        self.ac_res = wx.CheckBox(calculation, label="Inclure la resistance AC (effet de peau)")
        self.ac_res.SetValue(bool(config_manager.get("include_ac_resistance")))
        calc_grid.Add(wx.StaticText(calculation, label=""), 0)
        calc_grid.Add(self.ac_res, 0)

        calc_sizer.Add(calc_grid, 0, wx.ALL | wx.EXPAND, 10)

        note = wx.StaticText(calculation,
                             label="L'epaisseur de cuivre et le dielectrique sont deduits\n"
                                   "de l'empilement reel de la carte.")
        note.SetForegroundColour(wx.Colour(110, 110, 110))
        calc_sizer.Add(note, 0, wx.ALL, 10)
        calculation.SetSizer(calc_sizer)
        notebook.AddPage(calculation, "Calcul")

        # -- Detection ------------------------------------------------------
        detection = wx.Panel(notebook)
        det_sizer = wx.BoxSizer(wx.VERTICAL)

        self.detect_planes = wx.CheckBox(
            detection, label="Detecter automatiquement les plans de reference")
        self.detect_planes.SetValue(bool(config_manager.get("detect_reference_planes")))
        det_sizer.Add(self.detect_planes, 0, wx.ALL, 10)

        det_sizer.Add(wx.StaticText(detection,
                                    label="Noms des nets de masse (separes par des virgules) :"),
                      0, wx.ALL, 5)
        self.ground_names = wx.TextCtrl(
            detection, value=", ".join(config_manager.get("ground_net_names")))
        det_sizer.Add(self.ground_names, 0, wx.ALL | wx.EXPAND, 10)

        self.default_h = wx.SpinCtrlDouble(
            detection, value=str(config_manager.get("default_dielectric_mm")),
            min=0.02, max=5.0, inc=0.05)
        det_sizer.Add(wx.StaticText(detection,
                                    label="H dielectrique de repli (mm), detection desactivee :"),
                      0, wx.ALL, 5)
        det_sizer.Add(self.default_h, 0, wx.ALL | wx.EXPAND, 10)

        detection.SetSizer(det_sizer)
        notebook.AddPage(detection, "Detection")

        # -- Coplanaire -----------------------------------------------------
        coplanar = wx.Panel(notebook)
        cop_sizer = wx.BoxSizer(wx.VERTICAL)
        cop_grid = wx.FlexGridSizer(cols=2, vgap=10, hgap=15)
        cop_grid.AddGrowableCol(1)

        self.cpw_gap = wx.SpinCtrlDouble(coplanar,
                                         value=str(config_manager.get("cpw_gap_mm")),
                                         min=0.0, max=5.0, inc=0.05)
        cop_grid.Add(wx.StaticText(coplanar, label="Ecart coplanaire (mm, 0 = auto) :"), 0,
                     wx.ALIGN_RIGHT | wx.ALIGN_CENTER_VERTICAL)
        cop_grid.Add(self.cpw_gap, 0, wx.EXPAND)

        self.antipad = wx.SpinCtrlDouble(
            coplanar, value=str(config_manager.get("antipad_clearance_mm")),
            min=0.05, max=3.0, inc=0.05)
        cop_grid.Add(wx.StaticText(coplanar, label="Marge anti-pad des vias (mm) :"), 0,
                     wx.ALIGN_RIGHT | wx.ALIGN_CENTER_VERTICAL)
        cop_grid.Add(self.antipad, 0, wx.EXPAND)

        cop_sizer.Add(cop_grid, 0, wx.ALL | wx.EXPAND, 10)
        note_cop = wx.StaticText(
            coplanar,
            label="L'ecart coplanaire auto reprend la clearance du netclass.\n"
                  "La marge anti-pad sert au calcul de C_via.")
        note_cop.SetForegroundColour(wx.Colour(110, 110, 110))
        cop_sizer.Add(note_cop, 0, wx.ALL, 10)
        coplanar.SetSizer(cop_sizer)
        notebook.AddPage(coplanar, "Coplanaire")

        sizer.Add(notebook, 1, wx.ALL | wx.EXPAND, 10)

        buttons = wx.BoxSizer(wx.HORIZONTAL)
        buttons.Add(wx.Button(panel, wx.ID_OK, "Sauvegarder"), 0, wx.ALL, 5)
        buttons.Add(wx.Button(panel, wx.ID_CANCEL, "Annuler"), 0, wx.ALL, 5)
        sizer.Add(buttons, 0, wx.ALIGN_CENTER | wx.ALL, 10)

        panel.SetSizer(sizer)
        self.Centre()

    def save_config(self):
        """Recopie les widgets dans le gestionnaire puis persiste."""
        self.config.set("copper_oz", self.copper_oz.GetValue())
        self.config.set("temp_c", self.temp_c.GetValue())
        self.config.set("er_fr4", self.er_fr4.GetValue())
        self.config.set("freq_mhz", self.freq_mhz.GetValue())
        self.config.set("include_ac_resistance", self.ac_res.IsChecked())
        self.config.set("detect_reference_planes", self.detect_planes.IsChecked())
        self.config.set("default_dielectric_mm", self.default_h.GetValue())
        self.config.set("cpw_gap_mm", self.cpw_gap.GetValue())
        self.config.set("antipad_clearance_mm", self.antipad.GetValue())
        names = [n.strip() for n in self.ground_names.GetValue().split(",")]
        self.config.set("ground_net_names", [n for n in names if n])
        self.config._normalise()
        return self.config.save()


class ResultDialog(wx.Dialog):
    """Fenetre de resultats : resume, details, modeles, configuration."""

    def __init__(self, parent, results, via1_info, via2_info, config):
        super().__init__(parent, title="Calculateur de parasites PCB - Resultats",
                         size=(700, 760),
                         style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)

        panel = wx.Panel(self)
        sizer = wx.BoxSizer(wx.VERTICAL)

        header = wx.StaticText(panel, label="Analyse entre %s et %s" % (via1_info, via2_info))
        font = header.GetFont()
        font.SetPointSize(12)
        font.SetWeight(wx.FONTWEIGHT_BOLD)
        header.SetFont(font)
        sizer.Add(header, 0, wx.ALL | wx.CENTER, 10)

        notebook = wx.Notebook(panel)
        notebook.AddPage(self._build_summary(notebook, results, config), "Resume")
        notebook.AddPage(self._build_text_page(notebook, results["details"], True),
                         "Details par element")
        notebook.AddPage(self._build_text_page(notebook, self._models_text(results), True),
                         "Modeles et formules")
        notebook.AddPage(self._build_text_page(notebook, self._config_text(config, results), False),
                         "Configuration")
        sizer.Add(notebook, 1, wx.ALL | wx.EXPAND, 10)

        buttons = wx.BoxSizer(wx.HORIZONTAL)
        close_button = wx.Button(panel, wx.ID_OK, "Fermer")
        close_button.SetDefault()
        buttons.Add(close_button, 0, wx.ALL, 10)
        sizer.Add(buttons, 0, wx.ALIGN_CENTER)

        panel.SetSizer(sizer)
        self.Centre()

    def _build_summary(self, parent, results, config):
        page = wx.Panel(parent)
        sizer = wx.BoxSizer(wx.VERTICAL)

        geometry = wx.FlexGridSizer(cols=2, vgap=8, hgap=15)
        geometry.AddGrowableCol(1)
        rows = [
            ("Longueur piste", "%.3f mm" % results["track_length_mm"]),
            ("Longueur via", "%.3f mm" % results["via_length_mm"]),
            ("Longueur totale", "%.3f mm" % results["length_mm"]),
            ("Largeur principale", "%.3f mm" % results["width_mm"]),
            ("Couches traversees", str(results["layers"])),
            ("Elements", str(results["segments"])),
            ("Vias", str(results["via_count"])),
        ]
        for label, value in rows:
            geometry.Add(wx.StaticText(page, label=label + " :"), 0, wx.ALIGN_RIGHT)
            geometry.Add(wx.StaticText(page, label=value), 0)
        sizer.Add(geometry, 0, wx.ALL | wx.EXPAND, 15)

        box = wx.StaticBox(page, label="Valeurs parasites calculees")
        box_sizer = wx.StaticBoxSizer(box, wx.VERTICAL)
        grid = wx.FlexGridSizer(cols=2, vgap=12, hgap=20)
        grid.AddGrowableCol(1)

        entries = [
            ("Resistance DC", fmt_value(results["resistance_ohm"]) + "Ohm",
             wx.Colour(200, 50, 50)),
            ("Inductance", fmt_value(results["inductance_h"]) + "H", wx.Colour(50, 100, 200)),
            ("Capacite", fmt_value(results["capacitance_f"]) + "F", wx.Colour(50, 150, 50)),
        ]
        if results["resistance_ac_ohm"] > results["resistance_ohm"] * 1.001:
            entries.insert(1, (
                "Resistance AC @ %.1f MHz" % config.get("freq_mhz"),
                fmt_value(results["resistance_ac_ohm"]) + "Ohm", wx.Colour(180, 80, 80)))
        if results["impedance_ohm"] > 0:
            entries.append(("Z0 (segment principal)", "%.2f Ohm" % results["impedance_ohm"],
                            wx.Colour(100, 50, 150)))
        if results["delay_s"] > 0:
            entries.append(("Retard de propagation", fmt_value(results["delay_s"]) + "s",
                            wx.Colour(100, 100, 100)))
        elif results["inductance_h"] > 0 and results["resistance_ohm"] > 0:
            tau = results["inductance_h"] / results["resistance_ohm"]
            entries.append(("Constante de temps L/R", fmt_value(tau) + "s",
                            wx.Colour(100, 100, 100)))

        for label, value, colour in entries:
            text = wx.StaticText(page, label=value)
            font = text.GetFont()
            font.SetPointSize(11)
            font.SetWeight(wx.FONTWEIGHT_BOLD)
            text.SetFont(font)
            text.SetForegroundColour(colour)
            grid.Add(wx.StaticText(page, label=label + " :"), 0,
                     wx.ALIGN_RIGHT | wx.ALIGN_CENTER_VERTICAL)
            grid.Add(text, 0)

        box_sizer.Add(grid, 0, wx.ALL | wx.EXPAND, 15)
        sizer.Add(box_sizer, 0, wx.ALL | wx.EXPAND, 10)

        models = ", ".join("%s x%d" % (k, v) for k, v in sorted(results["model_counts"].items()))
        if models:
            sizer.Add(wx.StaticText(page, label="Modeles de ligne : " + models), 0, wx.ALL, 10)
        vias = ", ".join("%s x%d" % (k, v) for k, v in sorted(results["via_counts"].items()))
        if vias:
            sizer.Add(wx.StaticText(page, label="Types de via : " + vias), 0, wx.ALL, 10)

        note = wx.StaticText(
            page,
            label="Estimation quasi-statique. L et C sont deduits de Z0 et eps_eff du "
                  "modele retenu : Z0 = sqrt(L/C).")
        note.SetForegroundColour(wx.Colour(100, 100, 100))
        sizer.Add(note, 0, wx.ALL, 10)

        page.SetSizer(sizer)
        return page

    def _build_text_page(self, parent, text, monospace):
        page = wx.Panel(parent)
        sizer = wx.BoxSizer(wx.VERTICAL)
        control = wx.TextCtrl(page,
                              style=wx.TE_MULTILINE | wx.TE_READONLY | wx.HSCROLL,
                              size=(-1, 460))
        control.SetValue(text)
        if monospace:
            control.SetFont(wx.Font(9, wx.FONTFAMILY_TELETYPE,
                                    wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL))
        sizer.Add(control, 1, wx.ALL | wx.EXPAND, 5)
        page.SetSizer(sizer)
        return page

    def _models_text(self, results):
        lines = ["Modeles de ligne utilises pour ce chemin :", ""]
        for name, count in sorted(results["model_counts"].items()):
            lines.append("  - %s (%d segment(s))" % (name, count))
        if results["via_counts"]:
            lines.append("")
            lines.append("Types de via :")
            for name, count in sorted(results["via_counts"].items()):
                lines.append("  - %s (%d)" % (name, count))
        lines.append("")
        lines.append("Empilement deduit : %s" % " / ".join(results["stackup"]["layers"]))
        lines.append("  cuivre          : %.3f mm" % results["stackup"]["copper_mm"])
        lines.append("  dielectrique    : %.3f mm" % results["stackup"]["dielectric_mm"])
        lines.append("  epaisseur carte : %.3f mm" % results["stackup"]["total_mm"])
        lines.append("  ecart coplanaire: %.3f mm" % results["cpw_gap_mm"])
        lines.append("")
        lines.append("=" * 70)
        lines.append("FORMULES")
        lines.append("=" * 70)
        lines.append("Resistivite   rho(T) = 1.68e-8 * (1 + 0.00393*(T-20))")
        lines.append("Resistance DC R = rho(T) * l / (w * t)")
        lines.append("Epaisseur peau delta = sqrt(2*rho/(2*pi*f*mu0))")
        lines.append("Resistance AC R = rho * l / (2*(w+t)*delta)   si t >= 2*delta")
        lines.append("Piste isolee  L = (mu0*l/2pi)*[ln(2l/(w+t)) + 0.5 + (w+t)/(3l)]")
        lines.append("Microstrip    eps_eff = (er+1)/2 + (er-1)/2 * [1/sqrt(1+12h/w) + 0.04(1-w/h)^2]")
        lines.append("              Z0 = 60/sqrt(eps_eff) * ln(8h/w + w/(4h))        si w/h < 1")
        lines.append("              Z0 = 120*pi/(sqrt(eps_eff)*(w/h+1.393+0.667*ln(w/h+1.444)))")
        lines.append("Stripline     Z0 = 30*pi/sqrt(er) / (Weff/b + 0.4413)")
        lines.append("              Weff = w/b - (0.35-w/b)^2/(1+12*t/b)   si w/b < 0.35")
        lines.append("Stri. asym.   deux capacites : Co = CoL/2 + CoU/2, Lo = er/(Co*c^2)")
        lines.append("CPW / CPWG    Z0 = 30*pi/(sqrt(eps_eff) * K(k)/K'(k))")
        lines.append("              CPWG : eps_eff = (1+er*R1*R3)/(1+R1*R3),")
        lines.append("              R1 = K(k)/K'(k), R3 = K(k3)/K'(k3),")
        lines.append("              k3 = tanh(pi*a/2h)/tanh(pi*b/2h)")
        lines.append("Ligne         L' = Z0*sqrt(eps_eff)/c ; C' = sqrt(eps_eff)/(Z0*c)")
        lines.append("              => Z0 = sqrt(L/C) et L*C = eps_eff*(l/c)^2")
        lines.append("Retard        Td = l*sqrt(eps_eff)/c")
        lines.append("Via R         R = rho(T)*h/(pi*(R^2-r^2))")
        lines.append("Via L         L = (mu0*h/2pi)*[ln(4h/d) + 1]")
        lines.append("Via C         C = (1.41e-12/0.0254)*er*h*D1/(D2-D1)")
        lines.append("Empilement    h = (t_total - n*t_cu)/(n-1) ; pas = (t_total - t_cu)/(n-1)")
        lines.append("")
        lines.append("=" * 70)
        lines.append("SOURCES")
        lines.append("=" * 70)
        for topic, reference, url in SOURCES:
            lines.append("%s" % topic)
            lines.append("  %s" % reference)
            lines.append("  %s" % url)
        return "\n".join(lines)

    def _config_text(self, config, results):
        return "\n".join([
            "Parametres de calcul utilises :",
            "",
            "  Cuivre              : %.2f oz (%.1f um)" % (
                config.get("copper_oz"), config.get("copper_oz") * 35),
            "  Temperature         : %.1f degC" % config.get("temp_c"),
            "  Permittivite (er)   : %.2f" % config.get("er_fr4"),
            "  Frequence AC        : %.1f MHz" % config.get("freq_mhz"),
            "  Resistance AC       : %s" % (
                "activee" if config.get("include_ac_resistance") else "desactivee"),
            "  Detection des plans : %s" % (
                "activee" if config.get("detect_reference_planes") else "desactivee"),
            "  Nets de masse       : %s" % ", ".join(config.get("ground_net_names")),
            "  H de repli          : %.3f mm" % config.get("default_dielectric_mm"),
            "  Ecart coplanaire    : %.3f mm" % results["cpw_gap_mm"],
            "  Marge anti-pad      : %.3f mm" % config.get("antipad_clearance_mm"),
            "",
            "Empilement :",
            "  Couches cuivre      : %s" % " / ".join(results["stackup"]["layers"]),
            "  Epaisseur cuivre    : %.3f mm" % results["stackup"]["copper_mm"],
            "  Dielectrique calcule: %.3f mm" % results["stackup"]["dielectric_mm"],
            "  Epaisseur carte     : %.3f mm" % results["stackup"]["total_mm"],
        ])


# ---------------------------------------------------------------------------
# Plugin
# ---------------------------------------------------------------------------
class ParasiticPlugin(pcbnew.ActionPlugin):
    """Plugin principal KiCad."""

    def defaults(self):
        self.name = "Calculateur parasites R,L,C"
        self.category = "Analyse"
        self.description = ("Calcule R, L et C parasites entre deux vias selectionnes "
                            "(piste isolee, microstrip, stripline, coplanaire, vias).")
        self.show_toolbar_button = True
        self.config = None
        icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                 "parasitic_icon.png")
        if os.path.exists(icon_path):
            self.icon_file_name = icon_path

    def Run(self):
        self.config = ConfigManager()

        board = pcbnew.GetBoard()
        if board is None:
            wx.MessageBox("Aucune carte n'est ouverte.", "Calculateur de parasites",
                          wx.OK | wx.ICON_WARNING)
            return

        vias = [item for item in board.GetTracks()
                if isinstance(item, pcbnew.PCB_VIA) and item.IsSelected()]

        if len(vias) != 2:
            dialog = wx.MessageDialog(
                None,
                "Selectionnez exactement 2 vias avec Shift+Clic.\n\n"
                "Actuellement : %d via(s) selectionne(s).\n\n"
                "Voulez-vous ouvrir la configuration du plugin ?" % len(vias),
                "Selection requise",
                wx.YES_NO | wx.ICON_QUESTION)
            wants_config = dialog.ShowModal() == wx.ID_YES
            dialog.Destroy()
            if wants_config:
                self.show_config()
            return

        net1 = vias[0].GetNetCode()
        net2 = vias[1].GetNetCode()
        if net1 != net2 or net1 == 0:
            wx.MessageBox("Les deux vias doivent appartenir au meme net (et pas au net 0).",
                          "Erreur de net", wx.OK | wx.ICON_ERROR)
            return

        try:
            analyser = PathAnalyser(board, self.config)
            results = analyser.analyse(vias[0], vias[1])
        except Exception as exc:
            wx.MessageBox("Erreur lors de l'analyse :\n%s" % exc,
                          "Erreur", wx.OK | wx.ICON_ERROR)
            return

        self.show_results(results, vias[0], vias[1])

    def show_config(self):
        dialog = ConfigDialog(None, self.config)
        if dialog.ShowModal() == wx.ID_OK:
            ok, message = dialog.save_config()
            if ok:
                wx.MessageBox("Configuration sauvegardee.\n%s" % CONFIG_FILE,
                              "OK", wx.OK | wx.ICON_INFORMATION)
            else:
                wx.MessageBox(message, "Configuration non sauvegardee",
                              wx.OK | wx.ICON_WARNING)
        dialog.Destroy()

    def show_results(self, results, via1, via2):
        def describe(via):
            position = to_mm(via.GetPosition())
            return "Via @ (%.2f, %.2f) mm" % (position[0], position[1])

        dialog = ResultDialog(None, results, describe(via1), describe(via2), self.config)
        dialog.ShowModal()
        dialog.Destroy()


ParasiticPlugin().register()
