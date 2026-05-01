#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
KiCad Plugin : Calculateur avancé de parasites R, L, C des pistes PCB
Version 2.0 - Détection automatique des plans de masse + paramètres utilisateur
Compatible KiCad 7.x / 8.x
"""

import pcbnew
import wx
import math
import os
import json
from collections import deque

# Constantes physiques
RHO_CUIVRE_20C = 1.68e-8  # Ohm.m
TEMP_COEF_CUIVRE = 0.00393  # /°C
MU_0 = 4 * math.pi * 1e-7  # H/m
EPSILON_0 = 8.854e-12  # F/m
EPSILON_R_FR4 = 4.5

# Fichier de configuration
CONFIG_FILE = os.path.join(os.path.dirname(__file__), "parasitic_config.json")


class ConfigManager:
    """Gestionnaire de configuration persistante"""

    DEFAULTS = {
        'copper_oz': 1.0,
        'temp_c': 25.0,
        'default_dielectric_mm': 0.2,
        'er_fr4': 4.5,
        'freq_mhz': 100.0,
        'detect_ground_planes': True,
        'ground_net_names': ['GND', 'VSS', '0', 'GROUND', 'AGND', 'DGND'],
        'via_wall_thickness_um': 25.0,
        'include_ac_resistance': True,
        'show_intermediate_vias': True
    }

    def __init__(self):
        self.config = {}
        self.load()

    def load(self):
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, 'r') as f:
                    self.config = json.load(f)
            except:
                self.config = {}
        # Compléter avec les valeurs par défaut
        for key, val in self.DEFAULTS.items():
            if key not in self.config:
                self.config[key] = val

    def save(self):
        with open(CONFIG_FILE, 'w') as f:
            json.dump(self.config, f, indent=2)

    def get(self, key):
        return self.config.get(key, self.DEFAULTS.get(key))

    def set(self, key, value):
        self.config[key] = value


class GroundPlaneDetector:
    """Détecte les plans de masse et calcule les distances inter-couches"""

    def __init__(self, board, config):
        self.board = board
        self.config = config
        self.ground_nets = self._find_ground_nets()
        self.zones = self._extract_zones()
        self.layer_stack = self._build_layer_stack()

    def _find_ground_nets(self):
        """Trouve les nets de masse selon les noms configurés"""
        ground_names = self.config.get('ground_net_names')
        ground_nets = []
        for net in self.board.GetNetsByName().values():
            net_name = net.GetNetname()
            if any(g.lower() in net_name.lower() for g in ground_names):
                ground_nets.append(net.GetNetCode())
        return ground_nets

    def _extract_zones(self):
        """Extrait les zones de cuivre (plans)"""
        zones = []
        for zone in self.board.Zones():
            if zone.GetNetCode() in self.ground_nets:
                zones.append({
                    'layer': zone.GetLayer(),
                    'bbox': zone.GetBoundingBox(),
                    'net': zone.GetNetCode()
                })
        return zones

    def _build_layer_stack(self):
        """Construit la stackup des couches avec épaisseurs"""
        settings = self.board.GetDesignSettings()
        stack = []

        # Récupérer les couches cuivre
        copper_layers = list(settings.GetCopperLayerCount())

        # Épaisseur totale du PCB
        total_thickness = self._to_mm(settings.GetBoardThickness())

        # Approximation : épaisseur dielectrique uniforme entre couches
        if copper_layers > 0:
            dielectric_thickness = total_thickness / (copper_layers + 1)
        else:
            dielectric_thickness = total_thickness / 2

        # Construire la map couche -> distance au plan de masse
        layer_distances = {}

        for layer_id in range(pcbnew.PCBNEW_LAYER_ID_START, pcbnew.PCBNEW_LAYER_ID_START + 50):
            if not self.board.IsLayerEnabled(layer_id):
                continue

            layer_name = pcbnew.Board.GetStandardLayerName(layer_id)

            # Déterminer si c'est une couche interne ou externe
            if 'F.Cu' in layer_name:
                layer_distances[layer_id] = dielectric_thickness
            elif 'B.Cu' in layer_name:
                layer_distances[layer_id] = dielectric_thickness
            elif 'In' in layer_name or 'Inner' in layer_name:
                # Couche interne : distance au plan de masse le plus proche
                layer_num = self._extract_layer_number(layer_name)
                if layer_num is not None:
                    layer_distances[layer_id] = dielectric_thickness
                else:
                    layer_distances[layer_id] = dielectric_thickness
            else:
                layer_distances[layer_id] = self.config.get('default_dielectric_mm')

        return layer_distances

    def _extract_layer_number(self, layer_name):
        """Extrait le numéro de couche interne"""
        import re
        match = re.search(r'In(\d+)', layer_name)
        if match:
            return int(match.group(1))
        return None

    def get_distance_to_ground(self, layer_id, position=None):
        """
        Retourne la distance estimée au plan de masse le plus proche
        pour une couche donnée
        """
        if layer_id in self.layer_stack:
            return self.layer_stack[layer_id]

        # Fallback : chercher le plan de masse le plus proche
        if position and self.config.get('detect_ground_planes'):
            min_dist = float('inf')
            for zone in self.zones:
                if zone['bbox'].Contains(position):
                    # La zone contient le point, distance = 0 (sur le même layer)
                    # Mais on veut la distance au plan de masse ADJACENT
                    pass

            # Si pas de plan trouvé, utiliser la valeur par défaut
            if min_dist == float('inf'):
                return self.config.get('default_dielectric_mm')
            return min_dist

        return self.config.get('default_dielectric_mm')

    def _to_mm(self, wxpoint_or_int):
        """Convertit une coordonnée KiCad en mm"""
        if hasattr(wxpoint_or_int, 'x'):
            return (wxpoint_or_int.x / pcbnew.IU_PER_MM, 
                   wxpoint_or_int.y / pcbnew.IU_PER_MM)
        return wxpoint_or_int / pcbnew.IU_PER_MM


class ParasiticCalculator:
    """Moteur de calcul des parasites d'une piste PCB"""

    def __init__(self, config):
        self.config = config
        self.temp_c = config.get('temp_c')
        self.thickness_m = config.get('copper_oz') * 35e-6
        self.freq_hz = config.get('freq_mhz') * 1e6
        self.er = config.get('er_fr4')

        # Résistivité à la température de travail
        self.rho = RHO_CUIVRE_20C * (1 + TEMP_COEF_CUIVRE * (self.temp_c - 20))

    def resistance(self, length_m, width_m):
        """Résistance DC"""
        if width_m <= 0 or length_m <= 0:
            return 0.0
        section = width_m * self.thickness_m
        return self.rho * length_m / section

    def resistance_ac(self, length_m, width_m):
        """Résistance AC avec effet de peau"""
        r_dc = self.resistance(length_m, width_m)
        if not self.config.get('include_ac_resistance') or self.freq_hz <= 0:
            return r_dc

        omega = 2 * math.pi * self.freq_hz
        sigma = 1 / self.rho
        delta = math.sqrt(2 / (omega * MU_0 * sigma))

        if self.thickness_m < 2 * delta:
            return r_dc

        perimeter = 2 * (width_m + self.thickness_m)
        section_eff = perimeter * delta
        if section_eff <= 0:
            return r_dc

        r_ac = self.rho * length_m / section_eff
        return max(r_dc, r_ac)

    def inductance_microstrip(self, length_m, width_m, height_m):
        """Inductance microstrip (piste au-dessus d'un plan de masse)"""
        if length_m <= 0 or width_m <= 0 or height_m <= 0:
            return 0.0

        w_h = width_m / height_m

        # Formule de Schneider/Wheeler pour l'inductance
        if w_h < 1:
            l_per_m = (MU_0 / (2 * math.pi)) * math.log(2 * math.pi * height_m / width_m + 0.5)
        else:
            l_per_m = (MU_0 / (2 * math.pi)) * math.log(2 * height_m / width_m + 1)

        return l_per_m * length_m

    def capacite_microstrip(self, length_m, width_m, height_m):
        """Capacité piste-plan de masse (microstrip)"""
        if length_m <= 0 or width_m <= 0 or height_m <= 0:
            return 0.0

        w_h = width_m / height_m

        # Permittivité effective
        if w_h < 1:
            eff = (self.er + 1) / 2 + ((self.er - 1) / 2) * (1 / math.sqrt(1 + 12 * height_m / width_m) + 0.04 * (1 - w_h) ** 2)
        else:
            eff = (self.er + 1) / 2 + ((self.er - 1) / 2) * (1 / math.sqrt(1 + 12 * height_m / width_m))

        c_per_m = eff * EPSILON_0 * width_m / height_m
        return c_per_m * length_m

    def capacite_stripline(self, length_m, width_m, height_m):
        """Capacité stripline (piste entre deux plans de masse)"""
        if length_m <= 0 or width_m <= 0 or height_m <= 0:
            return 0.0

        # height_m = distance totale entre les deux plans
        c_per_m = (4 * EPSILON_0 * self.er * width_m) / height_m
        return c_per_m * length_m

    def impedance_microstrip(self, width_m, height_m):
        """Impédance caractéristique Z0 microstrip"""
        if width_m <= 0 or height_m <= 0:
            return 0.0

        w_h = width_m / height_m

        if w_h < 1:
            eff = (self.er + 1) / 2 + ((self.er - 1) / 2) * ((1 / math.sqrt(1 + 12 * height_m / width_m)) + 0.04 * (1 - width_m / height_m) ** 2)
            z0 = (60 / math.sqrt(eff)) * math.log(8 * height_m / width_m + 0.25 * width_m / height_m)
        else:
            eff = (self.er + 1) / 2 + ((self.er - 1) / 2) * (1 / math.sqrt(1 + 12 * height_m / width_m))
            z0 = (120 * math.pi) / (math.sqrt(eff) * (width_m / height_m + 1.393 + 0.667 * math.log(width_m / height_m + 1.444)))

        return z0

    def via_resistance(self, diam_mm, drill_mm, thickness_mm):
        """Résistance d'un via (cylindre creux)"""
        R = diam_mm / 2 * 1e-3
        r = drill_mm / 2 * 1e-3
        h = thickness_mm * 1e-3

        if R <= r:
            return 0.0

        section = math.pi * (R**2 - r**2)
        if section <= 0:
            return 0.0

        return RHO_CUIVRE_20C * h / section

    def via_inductance(self, diam_mm, thickness_mm):
        """Inductance d'un via"""
        r = diam_mm / 2 * 1e-3
        h = thickness_mm * 1e-3

        if r <= 0 or h <= 0:
            return 0.0

        return (MU_0 * h / (2 * math.pi)) * math.log(2 * h / r)


class ConfigDialog(wx.Dialog):
    """Fenêtre de configuration des paramètres de calcul"""

    def __init__(self, parent, config_manager):
        super().__init__(parent, title="Configuration du calculateur de parasites", 
                        size=(450, 550))

        self.config = config_manager
        panel = wx.Panel(self)
        sizer = wx.BoxSizer(wx.VERTICAL)

        # Notebook pour organiser
        notebook = wx.Notebook(panel)

        # === Onglet Matériaux ===
        mat_panel = wx.Panel(notebook)
        mat_sizer = wx.FlexGridSizer(cols=2, vgap=10, hgap=15)
        mat_sizer.AddGrowableCol(1)

        self.copper_oz = wx.SpinCtrlDouble(mat_panel, value=str(config_manager.get('copper_oz')), 
                                           min=0.5, max=4, inc=0.5)
        mat_sizer.Add(wx.StaticText(mat_panel, label="Cuivre (oz) :"), 0, wx.ALIGN_RIGHT | wx.ALIGN_CENTER_VERTICAL)
        mat_sizer.Add(self.copper_oz, 0, wx.EXPAND)

        self.temp_c = wx.SpinCtrlDouble(mat_panel, value=str(config_manager.get('temp_c')), 
                                        min=-40, max=150, inc=1)
        mat_sizer.Add(wx.StaticText(mat_panel, label="Température (°C) :"), 0, wx.ALIGN_RIGHT | wx.ALIGN_CENTER_VERTICAL)
        mat_sizer.Add(self.temp_c, 0, wx.EXPAND)

        self.er_fr4 = wx.SpinCtrlDouble(mat_panel, value=str(config_manager.get('er_fr4')), 
                                        min=3.0, max=6.0, inc=0.1)
        mat_sizer.Add(wx.StaticText(mat_panel, label="εᵣ FR4 :"), 0, wx.ALIGN_RIGHT | wx.ALIGN_CENTER_VERTICAL)
        mat_sizer.Add(self.er_fr4, 0, wx.EXPAND)

        self.default_h = wx.SpinCtrlDouble(mat_panel, value=str(config_manager.get('default_dielectric_mm')), 
                                           min=0.05, max=2.0, inc=0.05)
        mat_sizer.Add(wx.StaticText(mat_panel, label="H diélectrique défaut (mm) :"), 0, wx.ALIGN_RIGHT | wx.ALIGN_CENTER_VERTICAL)
        mat_sizer.Add(self.default_h, 0, wx.EXPAND)

        mat_panel.SetSizer(mat_sizer)
        notebook.AddPage(mat_panel, "Matériaux")

        # === Onglet Calcul ===
        calc_panel = wx.Panel(notebook)
        calc_sizer = wx.FlexGridSizer(cols=2, vgap=10, hgap=15)
        calc_sizer.AddGrowableCol(1)

        self.freq_mhz = wx.SpinCtrlDouble(calc_panel, value=str(config_manager.get('freq_mhz')), 
                                          min=0.1, max=10000, inc=1)
        calc_sizer.Add(wx.StaticText(calc_panel, label="Fréquence (MHz) :"), 0, wx.ALIGN_RIGHT | wx.ALIGN_CENTER_VERTICAL)
        calc_sizer.Add(self.freq_mhz, 0, wx.EXPAND)

        self.ac_res = wx.CheckBox(calc_panel, label="Inclure résistance AC (effet de peau)")
        self.ac_res.SetValue(config_manager.get('include_ac_resistance'))
        calc_sizer.Add(wx.StaticText(calc_panel, label=""), 0)
        calc_sizer.Add(self.ac_res, 0)

        calc_panel.SetSizer(calc_sizer)
        notebook.AddPage(calc_panel, "Calcul")

        # === Onglet Détection ===
        det_panel = wx.Panel(notebook)
        det_sizer = wx.BoxSizer(wx.VERTICAL)

        self.detect_gp = wx.CheckBox(det_panel, label="Détecter automatiquement les plans de masse")
        self.detect_gp.SetValue(config_manager.get('detect_ground_planes'))
        det_sizer.Add(self.detect_gp, 0, wx.ALL, 10)

        det_sizer.Add(wx.StaticText(det_panel, label="Noms des nets de masse (séparés par des virgules) :"), 0, wx.ALL, 5)
        self.ground_names = wx.TextCtrl(det_panel, value=", ".join(config_manager.get('ground_net_names')))
        det_sizer.Add(self.ground_names, 0, wx.ALL | wx.EXPAND, 10)

        det_panel.SetSizer(det_sizer)
        notebook.AddPage(det_panel, "Détection")

        sizer.Add(notebook, 1, wx.ALL | wx.EXPAND, 10)

        # Boutons
        btn_sizer = wx.BoxSizer(wx.HORIZONTAL)
        save_btn = wx.Button(panel, wx.ID_OK, "Sauvegarder")
        cancel_btn = wx.Button(panel, wx.ID_CANCEL, "Annuler")
        btn_sizer.Add(save_btn, 0, wx.ALL, 5)
        btn_sizer.Add(cancel_btn, 0, wx.ALL, 5)
        sizer.Add(btn_sizer, 0, wx.ALIGN_CENTER | wx.ALL, 10)

        panel.SetSizer(sizer)
        self.Centre()

    def save_config(self):
        """Sauvegarde les valeurs dans le gestionnaire"""
        self.config.set('copper_oz', self.copper_oz.GetValue())
        self.config.set('temp_c', self.temp_c.GetValue())
        self.config.set('er_fr4', self.er_fr4.GetValue())
        self.config.set('default_dielectric_mm', self.default_h.GetValue())
        self.config.set('freq_mhz', self.freq_mhz.GetValue())
        self.config.set('include_ac_resistance', self.ac_res.IsChecked())
        self.config.set('detect_ground_planes', self.detect_gp.IsChecked())

        names = [n.strip() for n in self.ground_names.GetValue().split(',')]
        self.config.set('ground_net_names', names)

        self.config.save()


class ResultDialog(wx.Dialog):
    """Fenêtre de résultats avancée"""

    def __init__(self, parent, results, via1_info, via2_info, config):
        super().__init__(parent, title="Calculateur de parasites PCB - Résultats", 
                        size=(600, 700), style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)

        panel = wx.Panel(self)
        sizer = wx.BoxSizer(wx.VERTICAL)

        # En-tête
        header = wx.StaticText(panel, label=f"Analyse entre {via1_info} et {via2_info}")
        font = header.GetFont()
        font.SetPointSize(12)
        font.SetWeight(wx.FONTWEIGHT_BOLD)
        header.SetFont(font)
        sizer.Add(header, 0, wx.ALL | wx.CENTER, 10)

        # Notebook
        notebook = wx.Notebook(panel)

        # === Onglet Résumé ===
        summary_panel = wx.Panel(notebook)
        summary_sizer = wx.BoxSizer(wx.VERTICAL)

        # Informations générales
        info_grid = wx.FlexGridSizer(cols=2, vgap=8, hgap=15)
        info_grid.AddGrowableCol(1)

        geo_data = [
            ("Longueur totale", f"{results['length_mm']:.3f} mm"),
            ("Largeur moyenne", f"{results['width_mm']:.3f} mm"),
            ("Couches traversées", str(results['layers'])),
            ("Nombre de segments", str(results['segments'])),
            ("Vias intermédiaires", str(results['via_count'])),
        ]

        for label, value in geo_data:
            info_grid.Add(wx.StaticText(summary_panel, label=label + " :"), 0, wx.ALIGN_RIGHT)
            info_grid.Add(wx.StaticText(summary_panel, label=value), 0)

        summary_sizer.Add(info_grid, 0, wx.ALL | wx.EXPAND, 15)

        # Valeurs électriques
        elec_box = wx.StaticBox(summary_panel, label="Valeurs parasites calculées")
        elec_sizer = wx.StaticBoxSizer(elec_box, wx.VERTICAL)

        elec_grid = wx.FlexGridSizer(cols=2, vgap=12, hgap=20)
        elec_grid.AddGrowableCol(1)

        # Résistance DC
        r_dc = results['resistance_ohm']
        r_text = wx.StaticText(summary_panel, label=f"{self._format_value(r_dc)}Ω")
        self._style_value(r_text, wx.Colour(200, 50, 50), 11)
        elec_grid.Add(wx.StaticText(summary_panel, label="Résistance DC :"), 0, wx.ALIGN_RIGHT | wx.ALIGN_CENTER_VERTICAL)
        elec_grid.Add(r_text, 0)

        # Résistance AC
        if 'resistance_ac_ohm' in results and results['resistance_ac_ohm'] != r_dc:
            r_ac = results['resistance_ac_ohm']
            r_ac_text = wx.StaticText(summary_panel, label=f"{self._format_value(r_ac)}Ω @ {config.get('freq_mhz'):.1f} MHz")
            self._style_value(r_ac_text, wx.Colour(180, 80, 80), 10)
            elec_grid.Add(wx.StaticText(summary_panel, label="Résistance AC :"), 0, wx.ALIGN_RIGHT | wx.ALIGN_CENTER_VERTICAL)
            elec_grid.Add(r_ac_text, 0)

        # Inductance
        l = results['inductance_h']
        l_text = wx.StaticText(summary_panel, label=f"{self._format_value(l)}H")
        self._style_value(l_text, wx.Colour(50, 100, 200), 11)
        elec_grid.Add(wx.StaticText(summary_panel, label="Inductance :"), 0, wx.ALIGN_RIGHT | wx.ALIGN_CENTER_VERTICAL)
        elec_grid.Add(l_text, 0)

        # Capacité
        c = results['capacitance_f']
        c_text = wx.StaticText(summary_panel, label=f"{self._format_value(c)}F")
        self._style_value(c_text, wx.Colour(50, 150, 50), 11)
        elec_grid.Add(wx.StaticText(summary_panel, label="Capacité :"), 0, wx.ALIGN_RIGHT | wx.ALIGN_CENTER_VERTICAL)
        elec_grid.Add(c_text, 0)

        # Impédance
        if results['impedance_ohm'] > 0:
            z_text = wx.StaticText(summary_panel, label=f"{results['impedance_ohm']:.2f} Ω")
            self._style_value(z_text, wx.Colour(100, 50, 150), 11)
            elec_grid.Add(wx.StaticText(summary_panel, label="Z₀ estimée :"), 0, wx.ALIGN_RIGHT | wx.ALIGN_CENTER_VERTICAL)
            elec_grid.Add(z_text, 0)

        # Constante de temps
        if l > 0 and c > 0:
            tau = math.sqrt(l * c)
            tau_text = wx.StaticText(summary_panel, label=f"{self._format_value(tau)}s")
            self._style_value(tau_text, wx.Colour(100, 100, 100), 10)
            elec_grid.Add(wx.StaticText(summary_panel, label="√(LC) :"), 0, wx.ALIGN_RIGHT | wx.ALIGN_CENTER_VERTICAL)
            elec_grid.Add(tau_text, 0)

        elec_sizer.Add(elec_grid, 0, wx.ALL | wx.EXPAND, 15)
        summary_sizer.Add(elec_sizer, 0, wx.ALL | wx.EXPAND, 10)

        # Note sur la précision
        note = wx.StaticText(summary_panel, label="Note : L et C sont des estimations basées sur la distance au plan de masse.")
        note.SetForegroundColour(wx.Colour(100, 100, 100))
        summary_sizer.Add(note, 0, wx.ALL, 10)

        summary_panel.SetSizer(summary_sizer)
        notebook.AddPage(summary_panel, "Résumé")

        # === Onglet Détails par segment ===
        details_panel = wx.Panel(notebook)
        details_sizer = wx.BoxSizer(wx.VERTICAL)

        details_text = wx.TextCtrl(details_panel, style=wx.TE_MULTILINE | wx.TE_READONLY | wx.HSCROLL,
                                   size=(-1, 400))
        details_text.SetValue(results['details'])
        details_text.SetFont(wx.Font(9, wx.FONTFAMILY_TELETYPE, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL))
        details_sizer.Add(details_text, 1, wx.ALL | wx.EXPAND, 5)

        details_panel.SetSizer(details_sizer)
        notebook.AddPage(details_panel, "Détails par segment")

        # === Onglet Configuration utilisée ===
        config_panel = wx.Panel(notebook)
        config_sizer = wx.BoxSizer(wx.VERTICAL)

        config_text = wx.TextCtrl(config_panel, style=wx.TE_MULTILINE | wx.TE_READONLY, size=(-1, 300))
        config_str = f"""Paramètres de calcul utilisés :
• Cuivre : {config.get('copper_oz')} oz ({config.get('copper_oz')*35:.0f} µm)
• Température : {config.get('temp_c')}°C
• εᵣ FR4 : {config.get('er_fr4')}
• Fréquence AC : {config.get('freq_mhz')} MHz
• Détection plans de masse : {'Oui' if config.get('detect_ground_planes') else 'Non'}
• H diélectrique défaut : {config.get('default_dielectric_mm')} mm
"""
        config_text.SetValue(config_str)
        config_sizer.Add(config_text, 1, wx.ALL | wx.EXPAND, 10)

        config_panel.SetSizer(config_sizer)
        notebook.AddPage(config_panel, "Configuration")

        sizer.Add(notebook, 1, wx.ALL | wx.EXPAND, 10)

        # Boutons
        btn_sizer = wx.BoxSizer(wx.HORIZONTAL)
        close_btn = wx.Button(panel, wx.ID_OK, "Fermer")
        close_btn.SetDefault()
        btn_sizer.Add(close_btn, 0, wx.ALL, 10)
        sizer.Add(btn_sizer, 0, wx.ALIGN_CENTER)

        panel.SetSizer(sizer)
        self.Centre()

    def _style_value(self, ctrl, color, size):
        font = ctrl.GetFont()
        font.SetPointSize(size)
        font.SetWeight(wx.FONTWEIGHT_BOLD)
        ctrl.SetFont(font)
        ctrl.SetForegroundColour(color)

    def _format_value(self, value):
        if value == 0:
            return "0 "
        abs_val = abs(value)
        if abs_val >= 1:
            return f"{value:.3f} "
        elif abs_val >= 1e-3:
            return f"{value*1e3:.3f} m"
        elif abs_val >= 1e-6:
            return f"{value*1e6:.3f} µ"
        elif abs_val >= 1e-9:
            return f"{value*1e9:.3f} n"
        elif abs_val >= 1e-12:
            return f"{value*1e12:.3f} p"
        else:
            return f"{value:.3e} "


class ParasiticPlugin(pcbnew.ActionPlugin):
    """Plugin principal KiCad"""

    def defaults(self):
        self.name = "Calculateur parasites R,L,C"
        self.category = "Analyse"
        self.description = "Calcule R, L, C parasites entre deux vias sélectionnés avec détection des plans de masse"
        self.show_toolbar_button = True
        icon_path = os.path.join(os.path.dirname(__file__), "parasitic_icon.png")
        if os.path.exists(icon_path):
            self.icon_file_name = icon_path

    def Run(self):
        board = pcbnew.GetBoard()
        self.config = ConfigManager()

        # Vérifier s'il y a une demande de configuration (Alt+clic ou autre)
        # Pour l'instant, on ajoute un menu contextuel simple

        # Récupérer la sélection
        selected_items = []
        for item in board.GetTracks():
            if item.IsSelected():
                selected_items.append(item)

        # Vérifier si l'utilisateur veut la configuration
        # (On pourrait détecter un modificateur, mais wx/KiCad est limité)
        # Alternative : toujours demander via un bouton dans la fenêtre de résultats

        # Filtrer les vias
        vias = [item for item in selected_items if isinstance(item, pcbnew.PCB_VIA)]

        if len(vias) != 2:
            # Proposer la configuration si aucune sélection valide
            dlg = wx.MessageDialog(
                None,
                f"Sélectionnez exactement 2 vias avec Shift+Clic.\n\n"
                f"Actuellement : {len(vias)} via(s) sélectionné(s).\n\n"
                f"Voulez-vous ouvrir la configuration du plugin ?",
                "Sélection requise",
                wx.YES_NO | wx.ICON_QUESTION
            )
            if dlg.ShowModal() == wx.ID_YES:
                self._show_config()
            dlg.Destroy()
            return

        via1, via2 = vias[0], vias[1]

        # Vérifier même net
        net1 = via1.GetNetCode()
        net2 = via2.GetNetCode()

        if net1 != net2 or net1 == 0:
            wx.MessageBox(
                "Les deux vias doivent appartenir au même net (et pas au net 0).",
                "Erreur de net",
                wx.OK | wx.ICON_ERROR
            )
            return

        try:
            results = self._analyze_path(board, via1, via2)
            self._show_results(results, via1, via2)
        except Exception as e:
            wx.MessageBox(f"Erreur lors de l'analyse :\n{str(e)}", "Erreur", wx.OK | wx.ICON_ERROR)

    def _show_config(self):
        """Affiche la fenêtre de configuration"""
        dlg = ConfigDialog(None, self.config)
        if dlg.ShowModal() == wx.ID_OK:
            dlg.save_config()
            wx.MessageBox("Configuration sauvegardée !", "OK", wx.OK | wx.ICON_INFORMATION)
        dlg.Destroy()

    def _analyze_path(self, board, via1, via2):
        """Analyse complète du chemin entre deux vias"""

        # Initialiser le détecteur de plans de masse
        ground_detector = GroundPlaneDetector(board, self.config)
        calc = ParasiticCalculator(self.config)

        net_code = via1.GetNetCode()
        all_tracks = [t for t in board.GetTracks() if t.GetNetCode() == net_code]

        # Construire le graphe et trouver le chemin
        path = self._find_path_bfs(board, via1, via2, all_tracks)

        if not path:
            raise ValueError("Aucun chemin continu trouvé entre les vias via les pistes connectées")

        total_length = 0.0
        total_r_dc = 0.0
        total_r_ac = 0.0
        total_l = 0.0
        total_c = 0.0

        details = []
        layers = set()
        via_count = 0
        last_width = 0.0

        pcb_thickness = self._to_mm(board.GetDesignSettings().GetBoardThickness())

        for i, segment in enumerate(path):
            if isinstance(segment, pcbnew.PCB_TRACK):
                start = self._to_mm(segment.GetStart())
                end = self._to_mm(segment.GetEnd())
                length = math.sqrt((end[0]-start[0])**2 + (end[1]-start[1])**2)
                width = self._to_mm(segment.GetWidth())
                layer = segment.GetLayer()
                layer_name = pcbnew.Board.GetStandardLayerName(layer)
                layers.add(layer_name)

                # Conversion en mètres
                length_m = length * 1e-3
                width_m = width * 1e-3
                last_width = width

                # Distance au plan de masse pour cette couche
                height_mm = ground_detector.get_distance_to_ground(layer, segment.GetStart())
                height_m = height_mm * 1e-3

                # Calculs
                r_dc = calc.resistance(length_m, width_m)
                r_ac = calc.resistance_ac(length_m, width_m)
                l = calc.inductance_microstrip(length_m, width_m, height_m)
                c = calc.capacite_microstrip(length_m, width_m, height_m)
                z0 = calc.impedance_microstrip(width_m, height_m)

                total_r_dc += r_dc
                total_r_ac += r_ac
                total_l += l
                total_c += c
                total_length += length

                details.append(
                    f"=== Segment {i+1}: Piste [{layer_name}] ===\n"
                    f"  Position: ({start[0]:.3f}, {start[1]:.3f}) -> ({end[0]:.3f}, {end[1]:.3f})\n"
                    f"  Longueur: {length:.3f} mm, Largeur: {width:.3f} mm\n"
                    f"  H plan masse: {height_mm:.3f} mm\n"
                    f"  R_DC: {self._fmt(r_dc)}Ω, R_AC: {self._fmt(r_ac)}Ω\n"
                    f"  L: {self._fmt(l)}H, C: {self._fmt(c)}F\n"
                    f"  Z₀: {z0:.1f} Ω\n"
                )

            elif isinstance(segment, pcbnew.PCB_VIA):
                via_count += 1
                pos = self._to_mm(segment.GetPosition())
                size = self._to_mm(segment.GetWidth())
                drill = self._to_mm(segment.GetDrillValue())

                # Résistance et inductance du via
                r_via = calc.via_resistance(size, drill, pcb_thickness)
                l_via = calc.via_inductance(size, pcb_thickness)

                total_r_dc += r_via
                total_r_ac += r_via  # Le via est peu affecté par l'effet de peau à HF moyennes
                total_l += l_via
                total_length += pcb_thickness  # Compte comme longueur verticale

                details.append(
                    f"=== Segment {i+1}: Via @ ({pos[0]:.3f}, {pos[1]:.3f}) ===\n"
                    f"  Diamètre: {size:.3f} mm, Perçage: {drill:.3f} mm\n"
                    f"  Épaisseur PCB: {pcb_thickness:.3f} mm\n"
                    f"  R_via: {self._fmt(r_via)}Ω, L_via: {self._fmt(l_via)}H\n"
                )

        return {
            'length_mm': total_length,
            'width_mm': last_width,
            'layers': len(layers),
            'segments': len(path),
            'via_count': via_count,
            'resistance_ohm': total_r_dc,
            'resistance_ac_ohm': total_r_ac,
            'inductance_h': total_l,
            'capacitance_f': total_c,
            'impedance_ohm': calc.impedance_microstrip(last_width * 1e-3, 
                                                        self.config.get('default_dielectric_mm') * 1e-3) if last_width > 0 else 0,
            'details': "\n".join(details)
        }

    def _find_path_bfs(self, board, start_via, end_via, tracks):
        """Trouve le chemin le plus court entre deux vias via BFS"""

        # Construire le graphe de connexion
        all_items = list(tracks) + [start_via, end_via]
        connections = {item: [] for item in all_items}

        # Indexer les positions pour accélérer
        pos_map = {}
        for item in all_items:
            if isinstance(item, pcbnew.PCB_TRACK):
                pos_map[item] = (item.GetStart(), item.GetEnd())
            elif isinstance(item, pcbnew.PCB_VIA):
                pos_map[item] = (item.GetPosition(), item.GetPosition())

        # Construire les connexions
        for i, item1 in enumerate(all_items):
            for item2 in all_items[i+1:]:
                if self._items_connected(item1, item2, pos_map):
                    connections[item1].append(item2)
                    connections[item2].append(item1)

        # BFS
        queue = deque([(start_via, [start_via])])
        visited = {start_via}

        while queue:
            current, path = queue.popleft()

            if current == end_via:
                return path

            for neighbor in connections.get(current, []):
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append((neighbor, path + [neighbor]))

        return []

    def _items_connected(self, item1, item2, pos_map):
        """Vérifie si deux items sont physiquement connectés"""
        if item1 is item2:
            return False

        p1_start, p1_end = pos_map[item1]
        p2_start, p2_end = pos_map[item2]

        # Vérifier toutes les combinaisons d'extrémités
        return (self._points_touch(p1_start, p2_start) or
                self._points_touch(p1_start, p2_end) or
                self._points_touch(p1_end, p2_start) or
                self._points_touch(p1_end, p2_end))

    def _points_touch(self, p1, p2, tolerance_nm=1000):
        """Vérifie si deux points sont suffisamment proches"""
        dx = abs(p1.x - p2.x)
        dy = abs(p1.y - p2.y)
        return dx <= tolerance_nm and dy <= tolerance_nm

    def _to_mm(self, wxpoint_or_int):
        """Convertit une coordonnée KiCad en mm"""
        if hasattr(wxpoint_or_int, 'x') and hasattr(wxpoint_or_int, 'y'):
            return (wxpoint_or_int.x / pcbnew.IU_PER_MM, 
                   wxpoint_or_int.y / pcbnew.IU_PER_MM)
        elif hasattr(wxpoint_or_int, 'x'):
            return wxpoint_or_int.x / pcbnew.IU_PER_MM
        return wxpoint_or_int / pcbnew.IU_PER_MM

    def _fmt(self, val):
        """Formatage compact"""
        if val == 0:
            return "0"
        if val < 1e-9:
            return f"{val*1e12:.2f}p"
        if val < 1e-6:
            return f"{val*1e9:.2f}n"
        if val < 1e-3:
            return f"{val*1e6:.2f}µ"
        if val < 1:
            return f"{val*1e3:.2f}m"
        return f"{val:.3f}"

    def _show_results(self, results, via1, via2):
        """Affiche la fenêtre de résultats"""
        pos1 = self._to_mm(via1.GetPosition())
        pos2 = self._to_mm(via2.GetPosition())
        via1_info = f"Via @ ({pos1[0]:.2f}, {pos1[1]:.2f}) mm"
        via2_info = f"Via @ ({pos2[0]:.2f}, {pos2[1]:.2f}) mm"

        dlg = ResultDialog(None, results, via1_info, via2_info, self.config)
        dlg.ShowModal()
        dlg.Destroy()


# Enregistrement du plugin
ParasiticPlugin().register()
