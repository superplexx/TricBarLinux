import json, os, shutil, sys, tempfile, unittest, xml.etree.ElementTree as ET
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
import tricbar as t

FAKE = {"kwriteconfig6": "/bin/kw", "kreadconfig6": "/bin/kr", "qdbus6": "/bin/qd",
        "plasma-apply-desktoptheme": "/bin/pat", "busctl": "/bin/bc"}

class FakeRunner(t.Runner):
    """Simula um Plasma: responde as leituras e guarda os comandos."""
    def __init__(self, panels_json, theme="breeze-dark", blur=None):
        super().__init__(dry=False, log=lambda s: None)
        self.panels_json, self.theme, self.blur = panels_json, theme, blur or {}
    def run(self, cmd):
        self.history.append(cmd)
        exe = Path(cmd[0]).name
        if exe == "kr":
            key = cmd[cmd.index("--key") + 1]
            if key == "name": return 0, self.theme + "\n"
            return 0, self.blur.get(key, t.UNSET) + "\n"
        if exe == "qd" and "evaluateScript" in cmd[3]:
            if "JSON.stringify" in cmd[4]: return 0, self.panels_json + "\n"
            return 0, "\n"
        return 0, ""

class T(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        t.AUTOSTART_PATH = self.tmp / "autostart" / "tricbar.desktop"
        self.orig_which = t.shutil.which
        t.shutil.which = lambda n: FAKE.get(n)
        self.panels = json.dumps([{"id": 2, "location": "bottom", "lengthMode": "fill", "alignment": "left",
                                   "offset": 0, "floating": True}])
    def tearDown(self):
        t.shutil.which = self.orig_which
        shutil.rmtree(self.tmp, ignore_errors=True)

    def mk(self, **kw):
        r = FakeRunner(self.panels, **kw)
        return r, t.KDE(r), t.State(self.tmp / "state.json")

    def cmds(self, r):
        return [" ".join(c) for c in r.history]

    def test_svg_valid_and_all_elements(self):
        root = ET.fromstring(t.panel_svg(0xFFD60A, 0.4))
        ids = {e.get("id") for e in root}
        base = {"topleft","top","topright","left","center","right","bottomleft","bottom","bottomright"}
        allp = ("",) + t.PANEL_PREFIXES
        self.assertEqual(ids, {p + n for p in allp for n in base} | {p + "mask-" + n for p in allp for n in base})
        # mask-* sempre opacos: a area do painel nao pode depender da opacidade da cor
        masks = [e for e in root if "mask-" in e.get("id")]
        self.assertTrue(masks and all(e.get("fill-opacity") is None for e in masks))
        vis = [e for e in root if "mask-" not in e.get("id")]
        self.assertEqual({e.get("fill") for e in vis}, {"#FFD60A"})
        self.assertEqual({e.get("fill-opacity") for e in vis}, {"0.400"})

    def test_theme_files_and_json(self):
        name = t.write_theme(0, 0, 0.0, self.tmp / "themes")
        base = self.tmp / "themes" / name
        for rel in ("metadata.json", "metadata.desktop", "widgets/panel-background.svg",
                    "translucent/widgets/panel-background.svg", "opaque/widgets/panel-background.svg"):
            self.assertTrue((base / rel).is_file(), rel)
        self.assertEqual(json.loads((base / "metadata.json").read_text())["KPlugin"]["Id"], "TricBar0")

    def test_config_roundtrip_and_clamp(self):
        p = self.tmp / "c.ini"
        t.save_config(t.Config(mode="acrylic", color=0x123456, opacity=250, center=True, blur=99, noise=-3), p)
        c = t.load_config(p)
        self.assertEqual((c.mode, c.color, c.opacity, c.center, c.blur, c.noise), ("acrylic", 0x123456, 100, True, 15, 0))
        p.write_text("mode=banana\ncolor=zzz\nopacity=abc\n")
        c = t.load_config(p)
        self.assertEqual((c.mode, c.color, c.opacity), ("clear", 0, 60))

    def test_hex(self):
        self.assertEqual(t.parse_hex("#ffd60a"), 0xFFD60A)
        self.assertIsNone(t.parse_hex("#fff")); self.assertIsNone(t.parse_hex("gggggg"))

    def test_busctl_parse(self):
        self.assertEqual(t.parse_busctl_string('s "[{\\"id\\":2}]\\n"\n'), '[{"id":2}]\n')

    def test_apply_blur_sequence_and_state(self):
        r, kde, st = self.mk(blur={"BlurStrength": "5", "blurEnabled": "true"})
        notes = t.apply(t.Config(mode="blur", color=0xFFD60A, opacity=40, blur=8), kde, st, self.tmp / "th")
        self.assertEqual(notes, [])
        cm = self.cmds(r)
        self.assertTrue(any(c.endswith("pat TricBar0") for c in cm))
        self.assertTrue(any("p.location = 'bottom'" in c and "p.floating = false" in c for c in cm))
        self.assertTrue(any("--key BlurStrength 8" in c for c in cm))
        self.assertTrue(any("--key NoiseStrength 0" in c for c in cm))
        self.assertTrue(any("--key blurEnabled true" in c for c in cm))
        self.assertTrue(any(c.endswith("/KWin reconfigure") for c in cm))
        self.assertEqual(st.data["original"]["theme"], "breeze-dark")
        self.assertEqual(st.data["original"]["blur"]["noise"], None)
        self.assertEqual(st.data["original"]["panels"][0]["lengthMode"], "fill")
        self.assertTrue(st.data["original"]["panels"][0]["floating"])
        svg = (self.tmp / "th" / "TricBar0" / "widgets" / "panel-background.svg").read_text()
        self.assertIn('fill-opacity="0.400"', svg)

    def test_restore_panel_layout_includes_floating_state(self):
        script = t.restore_panels_script([{
            "id": 2, "location": "top", "lengthMode": "fit",
            "alignment": "right", "offset": 10, "floating": True,
        }])
        self.assertIn("p.location = s.location", script)
        self.assertIn("p.floating = s.floating", script)

    def test_slots_alternate(self):
        r, kde, st = self.mk()
        for expect in ("TricBar0", "TricBar1", "TricBar0"):
            t.apply(t.Config(mode="color", opacity=100), kde, st, self.tmp / "th")
            self.assertTrue(self.cmds(r)[-1 - 0:] or True)
            self.assertTrue(any(c.endswith("pat " + expect) for c in self.cmds(r)[-6:]), expect)

    def test_acrylic_noise_and_clear(self):
        r, kde, st = self.mk()
        t.apply(t.Config(mode="acrylic", noise=9), kde, st, self.tmp / "th")
        self.assertTrue(any("--key NoiseStrength 9" in c for c in self.cmds(r)))
        t.apply(t.Config(mode="clear"), kde, st, self.tmp / "th")
        svg = (self.tmp / "th" / "TricBar1" / "widgets" / "panel-background.svg").read_text()
        self.assertIn('fill-opacity="0.000"', svg)
        # saiu do blur: restaura os valores originais (ausentes => --delete)
        self.assertTrue(any("--key BlurStrength --delete" in c for c in self.cmds(r)))

    def test_center_uses_spacers_not_fit(self):
        r, kde, st = self.mk()
        orig_eval = r.run
        def run(cmd):
            self.cmds_seen = getattr(self, "cmds_seen", [])
            if Path(cmd[0]).name == "qd" and "panelspacer" in cmd[4]:
                r.history.append(cmd); return 0, '{"2": [11, 12]}\n'
            return orig_eval(cmd)
        r.run = run
        t.apply(t.Config(mode="clear", center=True), kde, st, self.tmp / "th")
        scripts = [c[4] for c in r.history if len(c) > 4 and "panelspacer" in c[4]]
        self.assertEqual(len(scripts), 1)
        self.assertNotIn("'fit'", scripts[0])
        self.assertEqual(st.data["spacers"], {"2": [11, 12]})
        # reaplicar passa os ids existentes (o script nao duplica)
        t.apply(t.Config(mode="clear", center=True), kde, st, self.tmp / "th")
        self.assertIn('"2": [11, 12]', [c[4] for c in r.history if len(c) > 4 and "panelspacer" in c[4]][-1])
        n = len(r.history)
        t.apply(t.Config(mode="clear", center=False), kde, st, self.tmp / "th")
        self.assertTrue(any("w.remove()" in c[4] for c in r.history[n:] if len(c) > 4))
        self.assertEqual(st.data["spacers"], {})

    def test_center_reorders_existing_spacers_in_reverse_index_order(self):
        script = t.center_panels_script({"2": [11, 12]})
        self.assertIn("var have = old[pid] || []", script)
        self.assertIn("var launchers = [\"org.kde.plasma.kickoff\", \"org.kde.plasma.kicker\"]", script)
        self.assertIn("launcherWidgets[0].index = 0", script)
        self.assertIn("a.index = launcherWidgets[launcherWidgets.length - 1].index + 1", script)
        self.assertIn("if (a.index > taskWidgets[0].index) { a.index = taskWidgets[0].index; }", script)
        self.assertIn("b.index = lastTask.index + 1", script)
        self.assertNotIn("taskWidgets.forEach", script)

    def test_legacy_fit_panels_are_undone(self):
        r, kde, st = self.mk()
        st.data.update({"original": {"theme": "breeze-dark", "blur": {}, "panels":
                        [{"id": 2, "location": "bottom", "lengthMode": "fill", "alignment": "left", "offset": 0}]},
                        "panels_modified": True})
        t.apply(t.Config(mode="clear", center=False), kde, st, self.tmp / "th")
        self.assertTrue(any("saved.forEach" in " ".join(c) and '"lengthMode": "fill"' in " ".join(c) for c in r.history))
        self.assertFalse(st.data["panels_modified"])

    def test_parse_json_object(self):
        self.assertEqual(t.parse_json_object('x {"1": [2, 3]}\n'), {"1": [2, 3]})
        self.assertEqual(t.parse_json_object("{}"), {})
        self.assertIsNone(t.parse_json_object(None))

    def test_restore_all(self):
        r, kde, st = self.mk()
        t.apply(t.Config(mode="blur"), kde, st, self.tmp / "th")
        self.assertTrue((self.tmp / "th" / "TricBar0").exists())
        notes = t.restore_all(kde, st, self.tmp / "th")
        self.assertEqual(notes, [])
        self.assertTrue(any(c.endswith("pat breeze-dark") for c in self.cmds(r)))
        self.assertTrue(any("p.floating = s.floating" in c for c in self.cmds(r)))
        self.assertFalse((self.tmp / "th" / "TricBar0").exists())
        self.assertEqual(st.data, {})
        self.assertFalse((self.tmp / "state.json").exists())

    def test_theme_inherits_original_and_blur_flag(self):
        r, kde, st = self.mk(theme="breeze-dark")
        t.apply(t.Config(mode="clear"), kde, st, self.tmp / "th")
        rc = (self.tmp / "th" / "TricBar0" / "plasmarc").read_text()
        self.assertIn("FallbackTheme=breeze-dark", rc)
        self.assertIn("[BlurBehindEffect]\nenabled=false", rc)
        t.apply(t.Config(mode="acrylic"), kde, st, self.tmp / "th")
        self.assertIn("[BlurBehindEffect]\nenabled=true", (self.tmp / "th" / "TricBar1" / "plasmarc").read_text())

    def test_normal_reverts_when_current_theme_is_ours_even_without_flag(self):
        r, kde, st = self.mk(theme="TricBar0")
        st.data["original"] = {"theme": "breeze-dark", "blur": {}, "panels": []}
        t.apply(t.Config(mode="normal"), kde, st, self.tmp / "th")
        self.assertTrue(any(c.endswith("pat breeze-dark") for c in self.cmds(r)))

    def test_normal_does_nothing_if_untouched(self):
        r, kde, st = self.mk()
        t.apply(t.Config(mode="normal"), kde, st, self.tmp / "th")
        self.assertFalse(any(" pat " in c for c in self.cmds(r)))

    def test_original_theme_never_ours(self):
        r, kde, st = self.mk(theme="TricBar1")
        t.apply(t.Config(mode="clear"), kde, st, self.tmp / "th")
        self.assertEqual(st.data["original"]["theme"], "default")

    def test_startup_file_and_restore_removes_it(self):
        t.set_startup(True, cmd="/home/u/.local/bin/tricbar")
        txt = t.AUTOSTART_PATH.read_text()
        self.assertIn("Exec=/home/u/.local/bin/tricbar apply", txt)
        self.assertTrue(t.startup_enabled())
        r, kde, st = self.mk()
        t.apply(t.Config(mode="blur"), kde, st, self.tmp / "th")
        t.restore_all(kde, st, self.tmp / "th")
        self.assertFalse(t.startup_enabled())

    def test_startup_quotes_path_with_spaces(self):
        self.assertIn("Exec='/home/o t/tricbar' apply", t.autostart_text("/home/o t/tricbar"))

    def test_cli_dry_run_writes_nothing(self):
        t.CFG_PATH = self.tmp / "cli" / "config.ini"; t.STATE_PATH = self.tmp / "cli" / "state.json"
        rc = t.main(["--dry-run", "set", "--mode", "acrylic", "--color", "FFD60A", "--opacity", "30"])
        self.assertEqual(rc, 0)
        self.assertFalse((self.tmp / "cli").exists())

if __name__ == "__main__":
    unittest.main(verbosity=2)
