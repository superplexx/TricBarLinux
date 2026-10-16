#!/usr/bin/env python3
"""TricBar para KDE Plasma 6.

Deixa o painel do Plasma transparente, com Blur, Acrylic ou numa cor unica,
e (opcional) centraliza o painel como um dock.

No Linux nao existe motor nem DLL: o Plasma/KWin ja expoem tudo por comandos.
O TricBar so gera um Plasma Style com o fundo do painel na cor/opacidade
escolhidas, liga o efeito Blur do KWin e mexe no painel pela API de scripts do
Plasma. Depois de aplicar, nada fica rodando em segundo plano.

Uso:
    tricbar                      abre a janela
    tricbar apply                aplica ~/.config/tricbar/config.ini
    tricbar set --mode blur --color FFD60A --opacity 40 --blur 8
    tricbar set --startup 1      reaplica ao iniciar a sessao (0 desliga)
    tricbar restore              volta tudo ao que era antes
    tricbar status               mostra o que foi detectado
    --dry-run                    so mostra os comandos, nao executa
"""
from __future__ import annotations

import argparse
import ast
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Callable, Optional

APP = "tricbar"
VERSION = "1.2.0"

HOME = Path.home()
CFG_DIR = Path(os.environ.get("XDG_CONFIG_HOME", HOME / ".config")) / APP
CFG_PATH = CFG_DIR / "config.ini"
STATE_PATH = CFG_DIR / "state.json"
HOME_DATA = Path(os.environ.get("XDG_DATA_HOME", HOME / ".local" / "share"))
THEME_ROOT = Path(os.environ.get("XDG_DATA_HOME", HOME / ".local" / "share")) / "plasma" / "desktoptheme"
AUTOSTART_PATH = Path(os.environ.get("XDG_CONFIG_HOME", HOME / ".config")) / "autostart" / "tricbar.desktop"
THEME_PREFIX = "TricBar"  # os temas gerados se chamam TricBar0 e TricBar1 (alternam a cada aplicacao)

MODES = ("normal", "clear", "blur", "acrylic", "color")
MODE_NAMES = (
    "Normal (padrão do Plasma)",
    "Transparente",
    "Blur (desfoque)",
    "Acrylic (desfoque + ruído)",
    "Cor sólida",
)
PRESETS = (
    ("Preto", 0x000000),
    ("Branco", 0xFFFFFF),
    ("Amarelo", 0xFFD60A),
    ("Vermelho", 0xE81123),
    ("Verde", 0x10C040),
    ("Azul", 0x0078D4),
    ("Roxo", 0x8E44AD),
)

UNSET = "__tricbar_unset__"


# --------------------------------------------------------------------------- configuracao
@dataclass
class Config:
    mode: str = "clear"
    color: int = 0x000000      # 0xRRGGBB
    opacity: int = 60          # 0..100 (opacidade da cor)
    center: bool = False       # icones das tarefas centralizados (espacadores no painel)
    blur: int = 5              # forca do desfoque do KWin (1..15)
    noise: int = 6             # ruido do Acrylic no KWin (0..14)

    def normalized(self) -> "Config":
        mode = self.mode if self.mode in MODES else "clear"
        return replace(
            self,
            mode=mode,
            color=self.color & 0xFFFFFF,
            opacity=max(0, min(100, int(self.opacity))),
            blur=max(1, min(15, int(self.blur))),
            noise=max(0, min(14, int(self.noise))),
        )


def parse_hex(text: str) -> Optional[int]:
    s = text.strip().lstrip("#")
    if len(s) != 6:
        return None
    try:
        return int(s, 16)
    except ValueError:
        return None


def load_config(path: Path = CFG_PATH) -> Config:
    cfg = Config()
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return cfg
    for raw in lines:
        if "=" not in raw:
            continue
        key, _, val = raw.partition("=")
        key, val = key.strip().lower(), val.strip()
        try:
            if key == "mode":
                cfg.mode = val.lower()
            elif key == "color":
                c = parse_hex(val)
                if c is not None:
                    cfg.color = c
            elif key == "opacity":
                cfg.opacity = int(val)
            elif key == "center":
                cfg.center = val != "0"
            elif key == "blur":
                cfg.blur = int(val)
            elif key == "noise":
                cfg.noise = int(val)
        except ValueError:
            pass
    return cfg.normalized()


def save_config(cfg: Config, path: Path = CFG_PATH) -> None:
    cfg = cfg.normalized()
    path.parent.mkdir(parents=True, exist_ok=True)
    text = (
        f"mode={cfg.mode}\n"
        f"color={cfg.color:06X}\n"
        f"opacity={cfg.opacity}\n"
        f"center={1 if cfg.center else 0}\n"
        f"blur={cfg.blur}\n"
        f"noise={cfg.noise}\n"
    )
    tmp = path.with_suffix(".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)  # troca atomica


# --------------------------------------------------------------------------- estado (para restaurar)
class State:
    """Guarda como estava tudo antes do TricBar mexer, para o 'restaurar'."""

    def __init__(self, path: Path = STATE_PATH, dry: bool = False):
        self.path = path
        self.dry = dry
        self.data: dict = {}
        try:
            self.data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.data = {}

    def save(self) -> None:
        if self.dry:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, indent=2), encoding="utf-8")
        os.replace(tmp, self.path)

    def clear(self) -> None:
        self.data = {}
        if not self.dry:
            try:
                self.path.unlink()
            except OSError:
                pass


# --------------------------------------------------------------------------- execucao de comandos
class Runner:
    def __init__(self, dry: bool = False, log: Callable[[str], None] = print):
        self.dry = dry
        self.log = log
        self.history: list[list[str]] = []

    def run(self, cmd: list[str]) -> tuple[int, str]:
        self.history.append(cmd)
        shown = " ".join(shlex.quote(c) for c in cmd)
        if len(shown) > 400:
            shown = shown[:400] + " ..."
        self.log("$ " + shown)
        if self.dry:
            return 0, ""
        try:
            p = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        except FileNotFoundError:
            self.log("  (comando não encontrado)")
            return 127, ""
        except subprocess.TimeoutExpired:
            self.log("  (demorou demais)")
            return 124, ""
        out = (p.stdout or "").strip()
        err = (p.stderr or "").strip()
        if p.returncode != 0:
            self.log(f"  (código {p.returncode}) {err}")
        elif out and len(out) < 300:
            self.log("  " + out)
        return p.returncode, p.stdout or ""


def tool(*names: str) -> Optional[str]:
    for n in names:
        p = shutil.which(n)
        if p:
            return p
    return None


def parse_busctl_string(out: str) -> str:
    m = re.match(r'\s*s\s+(".*")\s*$', out, re.S)
    if not m:
        return out
    try:
        return ast.literal_eval(m.group(1))
    except (ValueError, SyntaxError):
        return m.group(1)[1:-1]


# --------------------------------------------------------------------------- KDE
READ_PANELS_SCRIPT = (
    "var out = [];"
    "panelIds.forEach(function (id) {"
    " var p = panelById(id);"
    " out.push({id: id, location: p.location, lengthMode: p.lengthMode,"
    " alignment: p.alignment, offset: p.offset, floating: p.floating});"
    "});"
    "print(JSON.stringify(out));"
)

# Centralizar os icones: o painel continua ocupando a largura toda (a janela do painel nao muda de
# tamanho, entao nao ha area clicavel velha nem painel "flutuando" mais alto) e dois Espacadores de
# painel expansivos, um de cada lado do Gerenciador de Tarefas, empurram os icones para o meio.
SPACER = "org.kde.plasma.panelspacer"
TASK_WIDGETS = ("org.kde.plasma.icontasks", "org.kde.plasma.taskmanager")
LAUNCHER_WIDGETS = ("org.kde.plasma.kickoff", "org.kde.plasma.kicker")


def normalize_task_panels_script() -> str:
    """Mantem os paineis das tarefas na borda inferior, em largura total e sem flutuar."""
    return (
        f"var tasks = {json.dumps(list(TASK_WIDGETS))};"
        "panelIds.forEach(function (pid) {"
        " var p = panelById(pid); if (!p) { return; }"
        " var hasTasks = false;"
        " p.widgetIds.forEach(function (id) {"
        "  var w = p.widgetById(id); if (w && tasks.indexOf(w.type) >= 0) { hasTasks = true; }"
        " });"
        " if (!hasTasks) { return; }"
        " p.location = 'bottom'; p.lengthMode = 'fill'; p.offset = 0; p.floating = false;"
        "});"
    )


def center_panels_script(old: dict) -> str:
    """Poe um espacador de cada lado das tarefas. 'old' = {painel: [idA, idB]} ja criados antes."""
    return (
        f"var old = {json.dumps(old)}; var out = {{}}; var tasks = {json.dumps(list(TASK_WIDGETS))};"
        f"var launchers = {json.dumps(list(LAUNCHER_WIDGETS))};"
        "function wid(p, id) { try { var w = p.widgetById(id); return (w && w.type) ? w : null; }"
        " catch (e) { return null; } }"
        "panelIds.forEach(function (pid) {"
        " var p = panelById(pid); if (!p) { return; }"
        " var have = old[pid] || []; var a = wid(p, have[0]); var b = wid(p, have[1]);"
        " if (!a || !b) {"
        "  have.forEach(function (i) { var w = wid(p, i); if (w) { w.remove(); } });"
        f"  a = p.addWidget('{SPACER}'); b = p.addWidget('{SPACER}');"
        " }"
        " var ws = []; p.widgetIds.forEach(function (id) {"
        "  var w = wid(p, id); if (w && w.id !== a.id && w.id !== b.id) { ws.push(w); }"
        " });"
        " ws.sort(function (x, y) { return x.index - y.index; });"
        " var taskWidgets = ws.filter(function (w) { return tasks.indexOf(w.type) >= 0; });"
        " if (!taskWidgets.length) { a.remove(); b.remove(); return; }"
        " var launcherWidgets = ws.filter(function (w) { return launchers.indexOf(w.type) >= 0; });"
        " launcherWidgets.sort(function (x, y) { return x.index - y.index; });"
        " if (launcherWidgets.length && launcherWidgets[launcherWidgets.length - 1].index > taskWidgets[0].index) {"
        "  launcherWidgets[0].index = 0;"
        " }"
        " if (launcherWidgets.length && a.index < launcherWidgets[launcherWidgets.length - 1].index + 1) {"
        "  a.index = launcherWidgets[launcherWidgets.length - 1].index + 1;"
        " }"
        " if (a.index > taskWidgets[0].index) { a.index = taskWidgets[0].index; }"
        " var lastTask = taskWidgets[taskWidgets.length - 1];"
        " if (b.index !== lastTask.index + 1) { b.index = lastTask.index + 1; }"
        " out[pid] = [a.id, b.id];"
        "});"
        "print(JSON.stringify(out));"
    )


def remove_spacers_script(ids: dict) -> str:
    return (
        f"var ids = {json.dumps(ids)};"
        "panelIds.forEach(function (pid) {"
        " var p = panelById(pid); var have = ids[pid]; if (!p || !have) { return; }"
        " have.forEach(function (i) { try { var w = p.widgetById(i); if (w && w.type) { w.remove(); } }"
        " catch (e) {} });"
        "});"
    )


def parse_json_object(txt: Optional[str]) -> Optional[dict]:
    if not txt:
        return None if txt is None else {}
    m = re.search(r"\{.*\}", txt, re.S)
    if not m:
        return {}
    try:
        v = json.loads(m.group(0))
    except ValueError:
        return None
    return v if isinstance(v, dict) else None


def restore_panels_script(saved: list[dict]) -> str:
    return (
        f"var saved = {json.dumps(saved)};"
        "saved.forEach(function (s) {"
        " var p = panelById(s.id);"
        " if (!p) { return; }"
        " if (s.location !== undefined) { p.location = s.location; }"
        " if (s.lengthMode !== undefined) { p.lengthMode = s.lengthMode; }"
        " if (s.alignment !== undefined) { p.alignment = s.alignment; }"
        " if (s.offset !== undefined) { p.offset = s.offset; }"
        " if (s.floating !== undefined) { p.floating = s.floating; }"
        "});"
    )


class KDE:
    def __init__(self, runner: Runner):
        self.r = runner

    # kconfig -------------------------------------------------------------
    def kwrite(self, file: str, group: tuple[str, ...], key: str, value: Optional[str]) -> bool:
        exe = tool("kwriteconfig6", "kwriteconfig5")
        if not exe:
            self.r.log("kwriteconfig6 não encontrado")
            return False
        cmd = [exe, "--file", file]
        for g in group:
            cmd += ["--group", g]
        cmd += ["--key", key]
        cmd += ["--delete"] if value is None else [value]
        return self.r.run(cmd)[0] == 0

    def kread(self, file: str, group: tuple[str, ...], key: str) -> Optional[str]:
        exe = tool("kreadconfig6", "kreadconfig5")
        if not exe:
            return None
        cmd = [exe, "--file", file]
        for g in group:
            cmd += ["--group", g]
        cmd += ["--key", key, "--default", UNSET]
        rc, out = self.r.run(cmd)
        out = out.strip()
        if rc != 0 or out == UNSET:
            return None
        return out

    # plasmashell ---------------------------------------------------------
    def plasma_eval(self, script: str) -> Optional[str]:
        q = tool("qdbus6", "qdbus-qt6", "qdbus")
        if q:
            rc, out = self.r.run([q, "org.kde.plasmashell", "/PlasmaShell",
                                  "org.kde.PlasmaShell.evaluateScript", script])
            return out.strip() if rc == 0 else None
        b = tool("busctl")
        if b:
            rc, out = self.r.run([b, "--user", "call", "org.kde.plasmashell", "/PlasmaShell",
                                  "org.kde.PlasmaShell", "evaluateScript", "s", script])
            return parse_busctl_string(out).strip() if rc == 0 else None
        self.r.log("nem qdbus6 nem busctl encontrados")
        return None

    def apply_theme(self, name: str) -> bool:
        exe = tool("plasma-apply-desktoptheme")
        if not exe:
            self.r.log("plasma-apply-desktoptheme não encontrado")
            return False
        return self.r.run([exe, name])[0] == 0

    # kwin ----------------------------------------------------------------
    def kwin_reconfigure(self) -> None:
        q = tool("qdbus6", "qdbus-qt6", "qdbus")
        if q:
            self.r.run([q, "org.kde.KWin", "/KWin", "reconfigure"])
            return
        b = tool("busctl")
        if b:
            self.r.run([b, "--user", "call", "org.kde.KWin", "/KWin", "org.kde.KWin", "reconfigure"])


# --------------------------------------------------------------------------- Plasma Style
PANEL_PREFIXES = ("north-", "south-", "west-", "east-", "floating-")


def panel_svg(rgb: int, alpha: float) -> str:
    """SVG minimo de um 'frame' do Plasma: 3x3 pixels, todos da mesma cor."""
    color = f"#{rgb & 0xFFFFFF:06X}"
    a = f"{max(0.0, min(1.0, alpha)):.3f}"
    cells = {
        "topleft": (0, 0), "top": (1, 0), "topright": (2, 0),
        "left": (0, 1), "center": (1, 1), "right": (2, 1),
        "bottomleft": (0, 2), "bottom": (1, 2), "bottomright": (2, 2),
    }
    # o Plasma escolhe o prefixo conforme a borda do painel (north/south/west/east) e se ele
    # flutua; sem prefixo vale para todos. Como todos tem o mesmo visual, repetimos os 9 quadrados.
    rects = "\n".join(
        f'  <rect id="{prefix}{name}" x="{x}" y="{y}" width="1" height="1" '
        f'fill="{color}" fill-opacity="{a}" shape-rendering="crispEdges"/>'
        for prefix in ("",) + PANEL_PREFIXES
        for name, (x, y) in cells.items()
    )
    # mask-*: sem eles o Plasma deduz a area do painel (desfoque e area clicavel) pela
    # transparencia da propria cor; com pouca opacidade a area encolhia e so a "pontinha" respondia.
    masks = "\n".join(
        f'  <rect id="{prefix}mask-{name}" x="{x}" y="{y}" width="1" height="1" fill="#000000"/>'
        for prefix in ("",) + PANEL_PREFIXES
        for name, (x, y) in cells.items()
    )
    rects = rects + "\n" + masks
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<svg xmlns="http://www.w3.org/2000/svg" width="3" height="3" viewBox="0 0 3 3">\n'
        f"{rects}\n</svg>\n"
    )


def theme_files(name: str, rgb: int, alpha: float, fallback: str = "default",
                blur: bool = False, version: str = VERSION) -> dict[str, str]:
    svg = panel_svg(rgb, alpha)
    meta = {
        "KPackageStructure": "Plasma/Theme",
        "KPlugin": {
            "Authors": [{"Name": "Superplex"}],
            "Description": "Fundo do painel gerado pelo TricBar",
            "Id": name,
            "License": "MIT",
            "Name": "TricBar",
            "Version": version,
        },
    }
    # plasmarc do tema: tudo que o TricBar nao desenha (botoes de tarefa, bandeja, dicas...)
    # continua vindo do Plasma Style que o usuario ja usava, e nao do Breeze padrao
    plasmarc = (
        "[Settings]\n"
        f"FallbackTheme={fallback}\n"
        "\n[BlurBehindEffect]\n"
        f"enabled={'true' if blur else 'false'}\n"
        "\n[ContrastEffect]\n"
        "enabled=false\n"
    )
    desktop = (
        "[Desktop Entry]\n"
        "Name=TricBar\n"
        "Comment=Fundo do painel gerado pelo TricBar\n"
        "X-KDE-PluginInfo-Author=Superplex\n"
        f"X-KDE-PluginInfo-Name={name}\n"
        f"X-KDE-PluginInfo-Version={version}\n"
        "X-KDE-PluginInfo-License=MIT\n"
    )
    return {
        "metadata.json": json.dumps(meta, indent=4) + "\n",
        "metadata.desktop": desktop,
        "plasmarc": plasmarc,
        # o Plasma escolhe a pasta conforme a opacidade do painel (adaptive/opaque/translucent):
        # as tres tem o mesmo visual, entao a escolha do usuario nao muda o resultado
        "widgets/panel-background.svg": svg,
        "translucent/widgets/panel-background.svg": svg,
        "opaque/widgets/panel-background.svg": svg,
    }


def write_theme(slot: int, rgb: int, alpha: float, root: Path = THEME_ROOT,
                fallback: str = "default", blur: bool = False) -> str:
    name = f"{THEME_PREFIX}{slot}"
    base = root / name
    shutil.rmtree(base, ignore_errors=True)  # nada de sobra de uma aplicacao anterior
    version = f"{VERSION}.{int(time.time())}"  # versao nova = o Plasma recarrega os SVGs do cache
    for rel, content in theme_files(name, rgb, alpha, fallback, blur, version).items():
        p = base / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    return name


# --------------------------------------------------------------------------- aplicar / restaurar
BLUR_KEYS = (
    ("enabled", "Plugins", "blurEnabled"),
    ("strength", "Effect-blur", "BlurStrength"),
    ("noise", "Effect-blur", "NoiseStrength"),
)


def capture_original(kde: KDE, state: State) -> None:
    theme = kde.kread("plasmarc", ("Theme",), "name") or "default"
    if theme.startswith(THEME_PREFIX):
        theme = "default"  # estado perdido: nao tratamos um tema nosso como o original
    blur = {k: kde.kread("kwinrc", (g,), key) for k, g, key in BLUR_KEYS}
    panels: list[dict] = []
    txt = kde.plasma_eval(READ_PANELS_SCRIPT)
    if txt:
        m = re.search(r"\[.*\]", txt, re.S)
        if m:
            try:
                panels = [p for p in json.loads(m.group(0)) if isinstance(p, dict) and "id" in p]
            except ValueError:
                panels = []
    state.data["original"] = {"theme": theme, "blur": blur, "panels": panels}


def restore_blur(kde: KDE, blur: dict) -> None:
    for k, g, key in BLUR_KEYS:
        kde.kwrite("kwinrc", (g,), key, blur.get(k))
    kde.kwin_reconfigure()


def apply(cfg: Config, kde: KDE, state: State, theme_root: Path = THEME_ROOT) -> list[str]:
    cfg = cfg.normalized()
    notes: list[str] = []
    st = state.data
    if "original" not in st:
        capture_original(kde, state)
    orig = st["original"]

    # 1) Plasma Style
    if cfg.mode == "normal":
        current = kde.kread("plasmarc", ("Theme",), "name") or ""
        if st.get("theme_modified") or current.startswith(THEME_PREFIX):
            if not kde.apply_theme(orig.get("theme", "default")):
                notes.append("Não consegui voltar o Plasma Style original.")
            st["theme_modified"] = False
    else:
        alpha = 0.0 if cfg.mode == "clear" else cfg.opacity / 100
        rgb = 0 if cfg.mode == "clear" else cfg.color
        # alterna entre TricBar0 e TricBar1: nome novo = o Plasma recarrega com certeza
        slot = (int(st["slot"]) + 1) % 2 if "slot" in st else 0
        if state.dry:
            name = f"{THEME_PREFIX}{slot}"
            kde.r.log(f"(dry-run) geraria o tema {name} em {theme_root}")
        else:
            name = write_theme(slot, rgb, alpha, theme_root,
                               fallback=orig.get("theme", "default"), blur=cfg.mode in ("blur", "acrylic"))
        if not kde.apply_theme(name):
            notes.append("Não consegui aplicar o Plasma Style (plasma-apply-desktoptheme).")
        st["slot"] = slot
        st["theme_modified"] = True

    # 2) Blur do KWin (global: vale para tudo que pede desfoque)
    if cfg.mode in ("blur", "acrylic"):
        kde.kwrite("kwinrc", ("Plugins",), "blurEnabled", "true")
        kde.kwrite("kwinrc", ("Effect-blur",), "BlurStrength", str(cfg.blur))
        kde.kwrite("kwinrc", ("Effect-blur",), "NoiseStrength", str(cfg.noise if cfg.mode == "acrylic" else 0))
        kde.kwin_reconfigure()
        st["blur_modified"] = True
    elif st.get("blur_modified"):
        restore_blur(kde, orig.get("blur", {}))
        st["blur_modified"] = False

    # 3) Centralizar os icones (espacadores)
    if st.get("panels_modified"):
        # versao antiga (1.1.0/1.1.1) encolhia o painel ("fit"): desfaz isso antes de tudo
        kde.plasma_eval(restore_panels_script(orig.get("panels", [])))
        st["panels_modified"] = False
    if kde.plasma_eval(normalize_task_panels_script()) is None:
        notes.append("Não consegui ajustar a posição do painel (API de scripts do Plasma não respondeu).")
    else:
        st["panel_layout_modified"] = True
    old = st.get("spacers") or {}
    if cfg.center:
        txt = kde.plasma_eval(center_panels_script(old))
        new = parse_json_object(txt)
        if new is None:
            notes.append("Não consegui centralizar os ícones (API de scripts do Plasma não respondeu).")
        elif not new:
            notes.append("Centralizar: não achei o Gerenciador de Tarefas em nenhum painel.")
        else:
            st["spacers"] = new
    elif old:
        kde.plasma_eval(remove_spacers_script(old))
        st["spacers"] = {}

    state.save()
    return notes


def restore_all(kde: KDE, state: State, theme_root: Path = THEME_ROOT) -> list[str]:
    notes: list[str] = []
    st = state.data
    orig = st.get("original")
    if not orig:
        notes.append("Nada para restaurar (o TricBar ainda não alterou nada).")
        return notes
    if not kde.apply_theme(orig.get("theme", "default")):
        notes.append("Não consegui voltar o Plasma Style original.")
    restore_blur(kde, orig.get("blur", {}))
    if st.get("spacers"):
        kde.plasma_eval(remove_spacers_script(st["spacers"]))
    if (st.get("panels_modified") or st.get("panel_layout_modified")) and orig.get("panels"):
        kde.plasma_eval(restore_panels_script(orig["panels"]))
    if not state.dry:
        for slot in (0, 1):
            shutil.rmtree(theme_root / f"{THEME_PREFIX}{slot}", ignore_errors=True)
    state.clear()
    if not state.dry:
        set_startup(False)  # senao o proximo login reaplicaria o estilo e desfaria o restaurar
    return notes


def describe(kde: KDE, state: State) -> str:
    theme = kde.kread("plasmarc", ("Theme",), "name") or "(padrão)"
    tools = {
        "kwriteconfig6": tool("kwriteconfig6", "kwriteconfig5"),
        "kreadconfig6": tool("kreadconfig6", "kreadconfig5"),
        "qdbus6/busctl": tool("qdbus6", "qdbus-qt6", "qdbus") or tool("busctl"),
        "plasma-apply-desktoptheme": tool("plasma-apply-desktoptheme"),
    }
    lines = [f"TricBar KDE {VERSION}", f"Plasma Style atual: {theme}"]
    lines += [f"{n}: {p or 'NÃO ENCONTRADO'}" for n, p in tools.items()]
    panels = kde.plasma_eval(READ_PANELS_SCRIPT)
    if panels:
        lines.append("Painéis: " + panels.strip())
    lines.append(f"Config: {CFG_PATH}")
    lines.append(f"Iniciar com a sessão: {'sim' if startup_enabled() else 'não'}")
    lines.append(f"Estado: {'alterado pelo TricBar' if state.data.get('original') else 'sem alterações'}")
    return "\n".join(lines)


# --------------------------------------------------------------------------- iniciar com a sessao
def self_command() -> str:
    """Caminho do comando 'tricbar' instalado (ou este proprio arquivo)."""
    return shutil.which(APP) or str(Path(__file__).resolve())


def autostart_text(cmd: str) -> str:
    return (
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Name=TricBar (reaplicar estilo do painel)\n"
        f"Exec={shlex.quote(cmd)} apply\n"
        "Icon=tricbar\n"
        "Terminal=false\n"
        "X-KDE-autostart-after=panel\n"
        "X-KDE-autostart-phase=2\n"
        "NoDisplay=true\n"
    )


def startup_enabled(path: Optional[Path] = None) -> bool:
    return (path or AUTOSTART_PATH).is_file()


def set_startup(on: bool, path: Optional[Path] = None, cmd: Optional[str] = None) -> None:
    path = path or AUTOSTART_PATH
    if on:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(autostart_text(cmd or self_command()), encoding="utf-8")
    else:
        try:
            path.unlink()
        except OSError:
            pass


def show_error(message: str) -> None:
    """Mostra o erro no terminal e, se nao houver terminal (clique no menu), numa janela."""
    print(message, file=sys.stderr)
    if sys.stderr.isatty():
        return
    for exe, args in (("kdialog", ["--title", "TricBar", "--error", message]),
                      ("zenity", ["--title=TricBar", "--error", "--no-markup", f"--text={message}"])):
        if shutil.which(exe):
            try:
                subprocess.run([exe, *args], timeout=600)
            except (OSError, subprocess.SubprocessError):
                pass
            return


# --------------------------------------------------------------------------- GUI (Qt6)
def load_qt():
    # PySide6 baixado pelo Setup numa pasta so do TricBar (fica por ultimo: o do sistema tem prioridade)
    lib = HOME_DATA / "tricbar" / "lib"
    if lib.is_dir() and str(lib) not in sys.path:
        sys.path.append(str(lib))
    try:
        from PySide6 import QtCore, QtGui, QtWidgets  # type: ignore
        return QtCore, QtGui, QtWidgets
    except ImportError:
        pass
    try:
        from PyQt6 import QtCore, QtGui, QtWidgets  # type: ignore
        return QtCore, QtGui, QtWidgets
    except ImportError:
        return None


def run_gui(dry: bool = False) -> int:
    qt = load_qt()
    if qt is None:
        show_error("Não achei PySide6 nem PyQt6.\n"
                   "Rode o Setup do TricBar de novo (ele baixa o PySide6), ou instale o pacote pyside6 da sua distro.\n"
                   "Sem interface você ainda pode usar: tricbar set --mode blur --opacity 40")
        return 2
    QtCore, QtGui, QtWidgets = qt
    Horizontal = QtCore.Qt.Orientation.Horizontal

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)

    class Window(QtWidgets.QWidget):
        def __init__(self) -> None:
            super().__init__()
            self.setWindowTitle("TricBar")
            self.setWindowIcon(QtGui.QIcon.fromTheme("tricbar", QtGui.QIcon.fromTheme("preferences-desktop-theme")))
            self.setWindowTitle(f"TricBar {VERSION}")
            self.setMinimumWidth(460)
            cfg = load_config(CFG_PATH)
            self.rgb = cfg.color
            self.loading = True

            lay = QtWidgets.QVBoxLayout(self)

            lay.addWidget(QtWidgets.QLabel("Estilo do painel"))
            self.cb_mode = QtWidgets.QComboBox()
            self.cb_mode.addItems(MODE_NAMES)
            self.cb_mode.setCurrentIndex(MODES.index(cfg.mode))
            self.cb_mode.currentIndexChanged.connect(self.update_enabled)
            lay.addWidget(self.cb_mode)

            lay.addWidget(QtWidgets.QLabel("Cor"))
            row = QtWidgets.QHBoxLayout()
            self.preview = QtWidgets.QFrame()
            self.preview.setFixedSize(40, 28)
            self.ed_hex = QtWidgets.QLineEdit()
            self.ed_hex.setMaxLength(7)
            self.ed_hex.setFixedWidth(100)
            self.ed_hex.textEdited.connect(self.hex_edited)
            btn_pick = QtWidgets.QPushButton("Escolher...")
            btn_pick.clicked.connect(self.pick_color)
            row.addWidget(self.preview)
            row.addWidget(self.ed_hex)
            row.addWidget(btn_pick)
            row.addStretch(1)
            lay.addLayout(row)

            prow = QtWidgets.QHBoxLayout()
            self.preset_buttons = []
            for name, rgb in PRESETS:
                b = QtWidgets.QPushButton()
                b.setFixedSize(34, 28)
                b.setToolTip(name)
                b.setStyleSheet(f"background:#{rgb:06x}; border:1px solid gray;")
                b.clicked.connect(lambda _=False, c=rgb: self.set_color(c))
                self.preset_buttons.append(b)
                prow.addWidget(b)
            prow.addStretch(1)
            lay.addLayout(prow)

            self.sl_opacity, self.lb_opacity = self.add_slider(lay, "Opacidade da cor", 0, 100, cfg.opacity, "%")
            self.sl_blur, self.lb_blur = self.add_slider(lay, "Força do desfoque", 1, 15, cfg.blur, "")
            self.sl_noise, self.lb_noise = self.add_slider(lay, "Ruído (Acrylic)", 0, 14, cfg.noise, "")

            self.chk_center = QtWidgets.QCheckBox("Centralizar os ícones das tarefas (espaçadores no painel)")
            self.chk_center.setChecked(cfg.center)
            lay.addWidget(self.chk_center)

            self.chk_startup = QtWidgets.QCheckBox("Reaplicar o estilo ao iniciar a sessão")
            self.chk_startup.setChecked(startup_enabled())
            self.chk_startup.toggled.connect(self.startup_toggled)
            lay.addWidget(self.chk_startup)

            btns = QtWidgets.QHBoxLayout()
            self.btn_apply = QtWidgets.QPushButton("Aplicar")
            self.btn_apply.clicked.connect(self.do_apply)
            self.btn_restore = QtWidgets.QPushButton("Restaurar padrão")
            self.btn_restore.clicked.connect(self.do_restore)
            btns.addWidget(self.btn_apply)
            btns.addWidget(self.btn_restore)
            lay.addLayout(btns)

            self.log = QtWidgets.QPlainTextEdit()
            self.log.setReadOnly(True)
            self.log.setMaximumHeight(130)
            self.log.setPlaceholderText("Os comandos executados aparecem aqui.")
            lay.addWidget(self.log)

            self.loading = False
            self.set_color(self.rgb)
            self.update_enabled()

        def add_slider(self, lay, title, lo, hi, val, suffix):
            label = QtWidgets.QLabel()
            slider = QtWidgets.QSlider(Horizontal)
            slider.setRange(lo, hi)
            slider.setValue(val)

            def upd(v: int, t=title, s=suffix, lb=label) -> None:
                lb.setText(f"{t}: {v}{s}")

            slider.valueChanged.connect(upd)
            upd(val)
            lay.addWidget(label)
            lay.addWidget(slider)
            return slider, label

        def startup_toggled(self, on: bool) -> None:
            if self.loading:
                return
            try:
                if not dry:
                    set_startup(on)
                self.append("Iniciar com a sessão: " + ("ligado" if on else "desligado"))
            except OSError as e:
                self.append(f"! Não consegui mexer no autostart: {e}")

        def set_color(self, rgb: int) -> None:
            self.rgb = rgb & 0xFFFFFF
            self.preview.setStyleSheet(f"background:#{self.rgb:06x}; border:1px solid gray;")
            self.ed_hex.setText(f"#{self.rgb:06X}")

        def hex_edited(self, text: str) -> None:
            c = parse_hex(text)
            if c is not None:
                self.rgb = c
                self.preview.setStyleSheet(f"background:#{c:06x}; border:1px solid gray;")

        def pick_color(self) -> None:
            c = QtWidgets.QColorDialog.getColor(QtGui.QColor.fromRgb(self.rgb), self, "Escolher cor")
            if c.isValid():
                self.set_color((c.red() << 16) | (c.green() << 8) | c.blue())

        def update_enabled(self) -> None:
            mode = MODES[self.cb_mode.currentIndex()]
            use_color = mode in ("blur", "acrylic", "color")
            for w in (self.preview, self.ed_hex, self.sl_opacity, self.lb_opacity, *self.preset_buttons):
                w.setEnabled(use_color)
            for w in (self.sl_blur, self.lb_blur):
                w.setEnabled(mode in ("blur", "acrylic"))
            for w in (self.sl_noise, self.lb_noise):
                w.setEnabled(mode == "acrylic")

        def current(self) -> Config:
            return Config(
                mode=MODES[self.cb_mode.currentIndex()],
                color=self.rgb,
                opacity=self.sl_opacity.value(),
                center=self.chk_center.isChecked(),
                blur=self.sl_blur.value(),
                noise=self.sl_noise.value(),
            ).normalized()

        def append(self, line: str) -> None:
            self.log.appendPlainText(line)
            QtWidgets.QApplication.processEvents()

        def busy(self, on: bool) -> None:
            self.btn_apply.setEnabled(not on)
            self.btn_restore.setEnabled(not on)
            QtWidgets.QApplication.processEvents()

        def do_apply(self) -> None:
            cfg = self.current()
            self.busy(True)
            try:
                save_config(cfg)
                state = State(STATE_PATH, dry=dry)
                notes = apply(cfg, KDE(Runner(dry, self.append)), state)
                for n in notes:
                    self.append("! " + n)
                self.append("Pronto." if not notes else "Terminou com avisos (veja acima).")
            finally:
                self.busy(False)

        def do_restore(self) -> None:
            self.busy(True)
            try:
                state = State(dry=dry)
                notes = restore_all(KDE(Runner(dry, self.append)), state)
                for n in notes:
                    self.append("! " + n)
                self.append("Restaurado." if not notes else "Terminou com avisos (veja acima).")
            finally:
                self.busy(False)

    w = Window()
    w.show()
    return app.exec()


# --------------------------------------------------------------------------- CLI
def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog=APP, description="Painel do Plasma transparente, Blur, Acrylic ou cor única.")
    ap.add_argument("--dry-run", action="store_true", help="só mostra os comandos, não executa nada")
    ap.add_argument("--version", action="version", version=f"%(prog)s {VERSION}")
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("gui", help="abre a janela (padrão)")
    sub.add_parser("apply", help=f"aplica o que está em {CFG_PATH}")
    sub.add_parser("restore", help="volta tudo ao que era antes do TricBar")
    sub.add_parser("status", help="mostra o que foi detectado")
    st = sub.add_parser("startup", help="liga/desliga reaplicar o estilo ao iniciar a sessão")
    st.add_argument("state", choices=("on", "off"))
    s = sub.add_parser("set", help="salva e aplica uma configuração")
    s.add_argument("--mode", choices=MODES)
    s.add_argument("--color", help="RRGGBB, ex.: FFD60A")
    s.add_argument("--opacity", type=int, help="0 a 100")
    s.add_argument("--blur", type=int, help="força do desfoque, 1 a 15")
    s.add_argument("--noise", type=int, help="ruído do Acrylic, 0 a 14")
    s.add_argument("--center", choices=("0", "1"), help="1 = centralizar os ícones das tarefas")
    s.add_argument("--startup", choices=("0", "1"), help="1 = reaplicar o estilo ao iniciar a sessão")
    return ap


def main(argv: Optional[list[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    cmd = args.cmd or "gui"
    dry = args.dry_run

    if cmd == "gui":
        return run_gui(dry)

    runner = Runner(dry)
    kde = KDE(runner)
    state = State(dry=dry)

    if cmd == "startup":
        if not dry:
            set_startup(args.state == "on")
        print(f"Iniciar com a sessão: {'ligado' if args.state == 'on' else 'desligado'}")
        return 0
    if cmd == "status":
        print(describe(kde, state))
        return 0
    if cmd == "restore":
        notes = restore_all(kde, state)
    elif cmd == "apply":
        notes = apply(load_config(CFG_PATH), kde, state)
    elif cmd == "set":
        cfg = load_config(CFG_PATH)
        if args.mode:
            cfg.mode = args.mode
        if args.color:
            c = parse_hex(args.color)
            if c is None:
                print("Cor inválida: use 6 dígitos hexadecimais, ex.: FFD60A", file=sys.stderr)
                return 2
            cfg.color = c
        if args.opacity is not None:
            cfg.opacity = args.opacity
        if args.blur is not None:
            cfg.blur = args.blur
        if args.noise is not None:
            cfg.noise = args.noise
        if args.center is not None:
            cfg.center = args.center == "1"
        cfg = cfg.normalized()
        if not dry:
            save_config(cfg)
            if args.startup is not None:
                set_startup(args.startup == "1")
        notes = apply(cfg, kde, state)
    else:
        return 2

    for n in notes:
        print("! " + n, file=sys.stderr)
    return 1 if notes else 0


if __name__ == "__main__":
    sys.exit(main())
