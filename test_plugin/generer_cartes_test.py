#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Generateur des cartes de test du plugin, avec composants et commentaires.

Chaque carte contient :
  - un contour de carte sur Edge.Cuts,
  - des footprints (connecteurs et resistances CMS) avec leurs pads,
  - un routage SIG reliant deux vias selectionnables,
  - des plans de cuivre GND selon le cas teste,
  - une documentation en francais sur la couche User.Comments.

Usage :
    python3 generer_cartes_test.py [dossier_de_sortie]

Les cartes sont ecrites en .kicad_pcb, directement ouvrables dans KiCad.
"""

import os
import sys

import pcbnew

MM = 1000000
OUT_DIR = os.path.dirname(os.path.abspath(__file__))


def mm(value):
    return int(round(value * MM))


def vec(x, y):
    return pcbnew.VECTOR2I(mm(x), mm(y))


class BoardBuilder:
    """Construction d'une carte de test complete."""

    def __init__(self, layers, thick_mm=1.6, width=160.0, height=100.0):
        self.board = pcbnew.CreateEmptyBoard()
        settings = self.board.GetDesignSettings()
        settings.SetCopperLayerCount(layers)
        settings.SetBoardThickness(mm(thick_mm))
        self.width = width
        self.height = height
        self.nets = {}
        for name in ("SIG", "GND", "+3V3"):
            net = pcbnew.NETINFO_ITEM(self.board, name)
            self.board.Add(net)
            self.nets[name] = net
        self._outline()

    # -- contour -----------------------------------------------------------
    def _outline(self):
        corners = [(5, 5), (5 + self.width, 5),
                   (5 + self.width, 5 + self.height), (5, 5 + self.height)]
        for index in range(4):
            start = corners[index]
            end = corners[(index + 1) % 4]
            shape = pcbnew.PCB_SHAPE(self.board)
            shape.SetShape(pcbnew.SHAPE_T_SEGMENT)
            shape.SetStart(vec(*start))
            shape.SetEnd(vec(*end))
            shape.SetLayer(pcbnew.Edge_Cuts)
            shape.SetWidth(mm(0.1))
            self.board.Add(shape)

    # -- documentation -----------------------------------------------------
    def comment(self, x, y, text, size=1.2, bold=False):
        item = pcbnew.PCB_TEXT(self.board)
        item.SetText(text)
        item.SetPosition(vec(x, y))
        item.SetLayer(pcbnew.Cmts_User)
        item.SetTextSize(pcbnew.VECTOR2I(mm(size), mm(size)))
        item.SetBold(bold)
        item.SetHorizJustify(pcbnew.GR_TEXT_H_ALIGN_LEFT)
        self.board.Add(item)
        return item

    def title(self, text, subtitle=None):
        self.comment(12, 12, text, size=2.4, bold=True)
        if subtitle:
            self.comment(12, 16.5, subtitle, size=1.5)

    # -- composants --------------------------------------------------------
    def footprint(self, library, name, reference, value, x, y, pads, net=None):
        """Cree un footprint avec ses pads.

        pads : liste de tuples (numero, decalage_x, decalage_y, largeur, hauteur,
                                 percage_mm, forme)
        net  : nom du net affecte aux pads (None = pad libre)
        """
        footprint = pcbnew.FOOTPRINT(self.board)
        footprint.SetReference(reference)
        footprint.SetValue(value)
        footprint.SetPosition(vec(x, y))
        footprint.SetLayer(pcbnew.F_Cu)
        try:
            footprint.SetFPID(pcbnew.LIB_ID(library, name))
        except Exception:
            pass

        for number, dx, dy, width, height, drill, shape in pads:
            pad = pcbnew.PAD(footprint)
            pad.SetNumber(str(number))
            pad.SetPosition(vec(x + dx, y + dy))
            pad.SetSize(pcbnew.VECTOR2I(mm(width), mm(height)))
            pad.SetShape(shape)
            if drill > 0:
                pad.SetAttribute(pcbnew.PAD_ATTRIB_PTH)
                pad.SetDrillSize(pcbnew.VECTOR2I(mm(drill), mm(drill)))
                pad.SetLayerSet(pad.PTHMask())
            else:
                pad.SetAttribute(pcbnew.PAD_ATTRIB_SMD)
                pad.SetLayerSet(pad.SMDMask())
            if net is not None:
                pad.SetNet(self.nets[net])
            footprint.Add(pad)

        self.board.Add(footprint)
        footprint.Reference().SetPosition(vec(x, y - 4))
        footprint.Value().SetPosition(vec(x, y + 4))
        return footprint

    def connector(self, reference, x, y, count=2, pitch=2.54, net="SIG"):
        """Borne a souder traversante, pas 2.54 mm."""
        pads = []
        for index in range(count):
            pads.append((index + 1, index * pitch, 0, 1.7, 1.7, 1.0, pcbnew.PAD_SHAPE_CIRCLE))
        return self.footprint("Connector_PinHeader_2.54mm",
                              "PinHeader_1x%02d_P2.54mm_Vertical" % count,
                              reference, "Conn_01x%02d" % count, x, y, pads, net=net)

    def resistor(self, reference, x, y, size="0603", net="SIG"):
        """Resistance CMS avec ses deux pads."""
        width, height = (0.9, 0.95) if size == "0603" else (1.2, 1.2)
        gap = 0.75 if size == "0603" else 1.0
        pads = [
            (1, -gap, 0, width, height, 0, pcbnew.PAD_SHAPE_ROUNDRECT),
            (2, gap, 0, width, height, 0, pcbnew.PAD_SHAPE_ROUNDRECT),
        ]
        return self.footprint("Resistor_SMD",
                              "R_%s_1608Metric" % size,
                              reference, "10k", x, y, pads, net=net)

    # -- routage -----------------------------------------------------------
    def track(self, net, x1, y1, x2, y2, layer, width=0.3):
        item = pcbnew.PCB_TRACK(self.board)
        item.SetStart(vec(x1, y1))
        item.SetEnd(vec(x2, y2))
        item.SetWidth(mm(width))
        item.SetLayer(layer)
        item.SetNet(self.nets[net])
        self.board.Add(item)
        return item

    def via(self, net, x, y, size=0.6, drill=0.3, top=None, bottom=None, kind=None):
        item = pcbnew.PCB_VIA(self.board)
        item.SetPosition(vec(x, y))
        item.SetWidth(mm(size))
        item.SetDrill(mm(drill))
        item.SetNet(self.nets[net])
        self.board.Add(item)
        if kind is not None:
            item.SetViaType(kind)
        if top is not None and bottom is not None:
            item.SetLayerPair(top, bottom)
        return item

    def zone(self, net, layer, x0, y0, x1, y1):
        zone = pcbnew.ZONE(self.board)
        zone.SetNet(self.nets[net])
        zone.SetLayer(layer)
        zone.SetIsRuleArea(False)
        outline = zone.Outline()
        outline.NewOutline()
        for x, y in ((x0, y0), (x1, y0), (x1, y1), (x0, y1)):
            outline.Append(mm(x), mm(y))
        self.board.Add(zone)
        return zone

    def save(self, filename):
        path = os.path.join(OUT_DIR, filename)
        self.board.Save(path)
        print("  %-32s %d pistes, %d vias, %d zones, %d footprints" % (
            filename,
            len([t for t in self.board.GetTracks() if not isinstance(t, pcbnew.PCB_VIA)]),
            len([t for t in self.board.GetTracks() if isinstance(t, pcbnew.PCB_VIA)]),
            len(list(self.board.Zones())),
            len(list(self.board.GetFootprints()))))
        return path


def case_microstrip():
    """Microstrip : piste F.Cu au-dessus d'un plan GND sur B.Cu."""
    builder = BoardBuilder(layers=2)
    builder.title("CAS 1 - MICROSTRIP",
                  "Piste F.Cu au-dessus du plan GND de B.Cu. Modele attendu : microstrip.")
    builder.comment(12, 21, "J1 - SIG --- 40 mm de piste 0.3 mm --- J2 - SIG", size=1.3)
    builder.comment(12, 24, "Plan GND continu sur B.Cu. H = 1.53 mm, er = 4.5.", size=1.3)

    builder.connector("J1", 20, 40)
    builder.connector("J2", 60, 40)
    builder.zone("GND", pcbnew.B_Cu, 5, 5, 165, 105)

    builder.via("SIG", 20, 40)
    builder.track("SIG", 20, 40, 60, 40, pcbnew.F_Cu)
    builder.via("SIG", 60, 40)
    return builder.save("t_microstrip.kicad_pcb")


def case_stripline():
    """Stripline symetrique : piste In1.Cu entre plans F.Cu et In2.Cu."""
    builder = BoardBuilder(layers=4)
    builder.title("CAS 2 - STRIPLINE SYMETRIQUE",
                  "Piste In1.Cu entre les plans F.Cu et In2.Cu. Modele : stripline symetrique.")
    builder.comment(12, 21, "Plans GND sur F.Cu et In2.Cu, piste sur In1.Cu.", size=1.3)
    builder.comment(12, 24, "b = 2 x h = 0.974 mm, er = 4.5.", size=1.3)

    builder.connector("J1", 20, 40)
    builder.connector("J2", 60, 40)
    builder.zone("GND", pcbnew.F_Cu, 5, 5, 165, 105)
    builder.zone("GND", pcbnew.In2_Cu, 5, 5, 165, 105)

    builder.via("SIG", 20, 40)
    builder.track("SIG", 20, 40, 60, 40, pcbnew.In1_Cu)
    builder.via("SIG", 60, 40)
    return builder.save("t_stripline.kicad_pcb")


def case_stripline_asym():
    """Stripline asymetrique : piste In1.Cu, plans F.Cu et In3.Cu."""
    builder = BoardBuilder(layers=6)
    builder.title("CAS 3 - STRIPLINE ASYMETRIQUE",
                  "Piste In1.Cu, plans F.Cu et In3.Cu : hauteurs haut/bas differentes.")
    builder.comment(12, 21, "Modele : methode des deux capacites (Steer).", size=1.3)

    builder.connector("J1", 20, 40)
    builder.connector("J2", 60, 40)
    builder.zone("GND", pcbnew.F_Cu, 5, 5, 165, 105)
    builder.zone("GND", pcbnew.In3_Cu, 5, 5, 165, 105)

    builder.via("SIG", 20, 40)
    builder.track("SIG", 20, 40, 60, 40, pcbnew.In1_Cu)
    builder.via("SIG", 60, 40)
    return builder.save("t_stripline_asym.kicad_pcb")


def case_cpw():
    """CPW : piste F.Cu entouree d'un plan GND coplanaire, sans plan arriere."""
    builder = BoardBuilder(layers=2)
    builder.title("CAS 4 - COPLANAIRE (CPW)",
                  "Piste F.Cu avec plan GND coplanaire, aucun plan sur B.Cu.")
    builder.comment(12, 21, "Modele : coplanaire Wen, ecart = clearance du netclass.", size=1.3)

    builder.connector("J1", 20, 40)
    builder.connector("J2", 60, 40)
    builder.zone("GND", pcbnew.F_Cu, 5, 5, 165, 105)

    builder.via("SIG", 20, 40)
    builder.track("SIG", 20, 40, 60, 40, pcbnew.F_Cu)
    builder.via("SIG", 60, 40)
    return builder.save("t_cpw.kicad_pcb")


def case_cpwg():
    """CPWG : plan coplanaire F.Cu et plan arriere In1.Cu."""
    builder = BoardBuilder(layers=4)
    builder.title("CAS 5 - COPLANAIRE AVEC PLAN ARRIERE (CPWG)",
                  "Plan GND coplanaire F.Cu et plan arriere In1.Cu.")
    builder.comment(12, 21, "Modele : Ghione-Naldi (CPWG).", size=1.3)

    builder.connector("J1", 20, 40)
    builder.connector("J2", 60, 40)
    builder.zone("GND", pcbnew.F_Cu, 5, 5, 165, 105)
    builder.zone("GND", pcbnew.In1_Cu, 5, 5, 165, 105)

    builder.via("SIG", 20, 40)
    builder.track("SIG", 20, 40, 60, 40, pcbnew.F_Cu)
    builder.via("SIG", 60, 40)
    return builder.save("t_cpwg.kicad_pcb")


def case_vias():
    """Chaine de vias : traversant, borgne, enterre, puis microvia isolee."""
    builder = BoardBuilder(layers=6)
    builder.title("CAS 6 - TYPES DE VIAS",
                  "Chaine traversant / borgne / enterre, plus une microvia isolee.")
    builder.comment(12, 21, "V1 traversant F.Cu-B.Cu, V2 borgne F.Cu-In3.Cu,", size=1.3)
    builder.comment(12, 24, "V3 enterre In2.Cu-In4.Cu, V4 borgne In4.Cu-B.Cu,", size=1.3)
    builder.comment(12, 27, "V5 traversant, puis microvia isolee F.Cu-In1.Cu.", size=1.3)

    builder.connector("J1", 15, 45)
    builder.track("SIG", 15, 45, 25, 45, pcbnew.F_Cu)
    builder.via("SIG", 25, 45, kind=pcbnew.VIATYPE_THROUGH)
    builder.track("SIG", 25, 45, 35, 45, pcbnew.F_Cu)
    builder.via("SIG", 35, 45, top=pcbnew.F_Cu, bottom=pcbnew.In3_Cu,
                kind=pcbnew.VIATYPE_BLIND)
    builder.track("SIG", 35, 45, 45, 45, pcbnew.In3_Cu)
    builder.via("SIG", 45, 45, top=pcbnew.In2_Cu, bottom=pcbnew.In4_Cu,
                kind=pcbnew.VIATYPE_BURIED)
    builder.track("SIG", 45, 45, 55, 45, pcbnew.In4_Cu)
    builder.via("SIG", 55, 45, top=pcbnew.In4_Cu, bottom=pcbnew.B_Cu,
                kind=pcbnew.VIATYPE_BLIND)
    builder.track("SIG", 55, 45, 65, 45, pcbnew.B_Cu)
    builder.via("SIG", 65, 45, kind=pcbnew.VIATYPE_THROUGH)
    builder.track("SIG", 65, 45, 75, 45, pcbnew.F_Cu)
    builder.connector("J2", 75, 45)
    builder.via("SIG", 110, 70, size=0.3, drill=0.15, top=pcbnew.F_Cu,
                bottom=pcbnew.In1_Cu, kind=pcbnew.VIATYPE_MICROVIA)
    return builder.save("t_vias.kicad_pcb")


def case_no_fake_path():
    """Deux pistes sur couches differentes avec extremites confondues."""
    builder = BoardBuilder(layers=4)
    builder.title("CAS 7 - PAS DE CHEMIN REEL",
                  "Pistes F.Cu et B.Cu dont les extremites se superposent.")
    builder.comment(12, 21, "Le plugin doit refuser ce chemin : aucune connexion", size=1.3)
    builder.comment(12, 24, "electrique reelle entre les deux couches.", size=1.3)

    builder.connector("J1", 20, 40)
    builder.connector("J2", 60, 40)
    builder.via("SIG", 20, 40)
    builder.track("SIG", 20, 40, 40, 40, pcbnew.F_Cu)
    builder.track("SIG", 40, 40, 60, 40, pcbnew.B_Cu)
    builder.via("SIG", 60, 40)
    return builder.save("t_no_fake_path.kicad_pcb")


def case_ground_match():
    """Nets pieges : +3V3 ne doit pas etre pris pour un net de masse."""
    builder = BoardBuilder(layers=2)
    builder.title("CAS 8 - DETECTION DES NETS DE MASSE",
                  "Le net +3V3 ne doit pas etre confondu avec un net de masse.")
    builder.comment(12, 21, "Le plan de masse est sur B.Cu, le net +3V3 est", size=1.3)
    builder.comment(12, 24, "un simple ilot : il ne doit pas etre detecte.", size=1.3)

    builder.connector("J1", 20, 40)
    builder.connector("J2", 60, 40)
    builder.zone("GND", pcbnew.B_Cu, 5, 5, 165, 105)
    builder.zone("+3V3", pcbnew.B_Cu, 100, 60, 140, 90)

    builder.via("SIG", 20, 40)
    builder.track("SIG", 20, 40, 60, 40, pcbnew.F_Cu)
    builder.via("SIG", 60, 40)
    return builder.save("t_ground_match.kicad_pcb")


def case_isolated():
    """Aucun plan de cuivre : le plugin doit retomber sur la piste isolee."""
    builder = BoardBuilder(layers=2)
    builder.title("CAS 9 - PISTE ISOLEE",
                  "Aucun plan de cuivre : modele Grover pour L, C non definie.")
    builder.comment(12, 21, "Le plugin doit afficher L sans C ni Z0.", size=1.3)

    builder.connector("J1", 20, 40)
    builder.connector("J2", 60, 40)
    builder.via("SIG", 20, 40)
    builder.track("SIG", 20, 40, 60, 40, pcbnew.F_Cu)
    builder.via("SIG", 60, 40)
    return builder.save("t_piste_isolee.kicad_pcb")


CASES = [
    case_microstrip,
    case_stripline,
    case_stripline_asym,
    case_cpw,
    case_cpwg,
    case_vias,
    case_no_fake_path,
    case_ground_match,
    case_isolated,
]


if __name__ == "__main__":
    if len(sys.argv) > 1:
        OUT_DIR = os.path.abspath(sys.argv[1])
        if not os.path.isdir(OUT_DIR):
            os.makedirs(OUT_DIR)
    print("Generation des cartes de test dans %s" % OUT_DIR)
    for case in CASES:
        case()
    print("Termine.")
