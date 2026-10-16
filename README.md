# TricBar para Linux (KDE Plasma 6)

### Portugues (BR)

Painel do Plasma **transparente**, com **Blur**, **Acrylic** ou numa **cor única** (amarelo, `#000000`, o que você quiser), e opção de **centralizar os ícones** das tarefas. Tem janela de configurações e linha de comando.

No Linux **não existe motor, DLL nem injeção em processo**: o Plasma e o KWin já têm comandos oficiais para tudo isso. Depois de aplicar, **nada fica rodando em segundo plano** (0 MB de RAM).

## O que mudou em relação ao Windows

| Windows (`TricBarBlur.exe` + DLL + Launcher) | KDE (`tricbar.py`) |
|---|---|
| Aplica o efeito na janela da barra a cada 1,5 s | Gera um **Plasma Style** com o fundo do painel na cor e opacidade escolhidas, e aplica uma vez |
| Transparente / Cor sólida | Fundo do painel com `fill-opacity` 0 ou a opacidade escolhida |
| Blur | Mesma cor + efeito **Blur do KWin** ligado (força configurável) |
| Acrylic | Blur do KWin + **ruído** (`NoiseStrength`) |
| Centralizar ícones | Dois **Espaçadores de painel** (um de cada lado do Gerenciador de Tarefas), pela API de scripts do Plasma 6; o painel continua na largura toda |
| DLL dentro do Explorer (XAML) | Não precisa |
| Ícone na bandeja | Não precisa |

## Instalar (Setup único)

Baixe **`TricBar-Setup-1.2.0.run`**, dê permissão e execute (ou clique com o botão direito → Propriedades → Permissões → "É executável" e dê duplo clique):

```bash
chmod +x TricBar-Setup-1.2.0.run
./TricBar-Setup-1.2.0.run
```

O assistente (janelas do KDE via `kdialog`) instala o app e os atalhos só para o seu usuário: app em `~/.local/bin/tricbar`, entradas do TricBar e do desinstalador no menu de aplicativos em `~/.local/share/applications`, ícone e opção de "reaplicar ao iniciar a sessão". Não cria atalhos na Área de Trabalho. Requer KDE Plasma 6 e Python 3.9+. Se faltar o PySide6 (janela de configurações) e também faltar o `pip`, o Setup instala o pacote de `pip` da distro usando `apt`, `dnf`/`yum`, `pacman`, `zypper`, `apk`, `xbps`, `emerge` ou `urpmi`, conforme disponível; essa etapa pode pedir autenticação administrativa. Depois baixa o PySide6 (~200 MB; precisa de internet) para `~/.local/share/tricbar/lib`, sem instalar o PySide6 no sistema; essa cópia some ao desinstalar.

Outras opções do Setup: `--uninstall` (ou o atalho **TricBar - Uninstall** no menu de aplicativos, ou o comando `tricbar-uninstall`), `--extract PASTA` (extrai o app e o ícone), `--check` (confere se o arquivo está íntegro), `-y` (sem perguntas), `--tty` (modo texto).

Para gerar o Setup a partir deste repositório: `./build-setup.sh` (precisa de Python com Pillow só para redimensionar o ícone).

## Usar

```bash
tricbar                                   # abre a janela
tricbar set --mode blur --color FFD60A --opacity 40 --blur 8
tricbar set --mode acrylic --color 000000 --opacity 50 --noise 8
tricbar set --mode clear                  # totalmente transparente
tricbar set --center 1                    # ícones das tarefas centralizados
tricbar set --startup 1                   # reaplica o estilo ao iniciar a sessão
tricbar restore                           # volta tudo ao que era antes
tricbar status                            # mostra o que foi detectado
tricbar --dry-run set --mode blur         # só mostra os comandos, não executa
```

Estilos: `normal`, `clear`, `blur`, `acrylic`, `color`. A configuração fica em `~/.config/tricbar/config.ini` (mesmas chaves do Windows: `mode`, `color`, `opacity`, `center`, mais `blur` e `noise`).

## O que o TricBar mexe (e como desfazer na mão)

| O quê | Onde | Como voltar |
|---|---|---|
| Plasma Style `TricBar0` / `TricBar1` | `~/.local/share/plasma/desktoptheme/` | `plasma-apply-desktoptheme breeze-dark` (ou o seu) e apague as duas pastas |
| Blur do KWin | `kwinrc`: `[Plugins] blurEnabled`, `[Effect-blur] BlurStrength`, `NoiseStrength` | `tricbar restore`, ou apague as chaves com `kwriteconfig6 --delete` |
| Posição do painel principal | Painel com Gerenciador de Tarefas: inferior, largura total e não flutuante | `tricbar restore` volta à posição e ao modo anteriores |
| Dois Espaçadores de painel (só com `--center 1`) | adicionados ao painel pela API de scripts, um de cada lado do Gerenciador de Tarefas | `tricbar restore` |
| Como estava antes | `~/.config/tricbar/state.json` | é lido pelo `restore` |

Se o painel ficar estranho, o caminho mais seguro é `tricbar restore`. Se o próprio Plasma travar: `systemctl --user restart plasma-plasmashell.service` (ou `plasmashell --replace &`).

## Limitações (leia antes)

- **O Plasma Style vira "TricBar".** Ele só define o fundo do painel; o resto cai no tema padrão. Se você usa outro Plasma Style, ele é trocado enquanto o TricBar estiver ativo e volta no `restore`.
- **O Blur é global do KWin**: a força e o ruído valem para tudo que pede desfoque, não só o painel. O efeito Blur precisa estar disponível nos Efeitos da Área de Trabalho.
- **"Centralizar" usa espaçadores**: o menu fica à esquerda e a bandeja à direita; as tarefas ficam no meio do espaço que sobra (centro exato só se os dois lados tiverem o mesmo tamanho). O TricBar guarda os espaçadores que criou e os remove ao desligar a opção ou em `restore`. Se você já tem espaçadores seus no painel, eles não são mexidos.
- Pensado para **Plasma 6**. No Plasma 5 a transparência pode funcionar, mas o modo centralizar não (`lengthMode` só existe a partir do 6.0).
- Alternativa pronta para ajustes mais finos: o widget *Panel Colorizer*.


### English (US)

# TricBar for Linux (KDE Plasma 6)

Make the Plasma panel **transparent**, add **Blur** or **Acrylic**, or set it to a **solid color** (yellow, `#000000`, or any color you like). You can also **center task icons**. TricBar includes a settings window and a command-line interface.

On Linux, there is **no engine, DLL, or process injection**: Plasma and KWin already provide official commands for everything TricBar needs. After applying your settings, **nothing runs in the background** (0 MB of RAM).

## How this differs from the Windows version

| Windows (`TricBarBlur.exe` + DLL + Launcher) | KDE (`tricbar.py`) |
|---|---|
| Applies the effect to the taskbar window every 1.5 seconds | Generates a **Plasma Style** with the panel background color and opacity you choose, then applies it once |
| Transparent / Solid color | Panel background with `fill-opacity` set to 0 or to your chosen opacity |
| Blur | Same color + KWin's **Blur effect** enabled (adjustable strength) |
| Acrylic | KWin Blur + **noise** (`NoiseStrength`) |
| Center icons | Adds two **Panel Spacers**, one on each side of the Task Manager, using the Plasma 6 scripting API; the panel remains full-width |
| DLL injected into Explorer (XAML) | Not needed |
| System tray icon | Not needed |

## Install (one-time setup)

Download **`TricBar-Setup-1.2.0.run`**, make it executable, and run it (or right-click → Properties → Permissions → "Is executable" and double-click):

```bash
chmod +x TricBar-Setup-1.2.0.run
./TricBar-Setup-1.2.0.run
```

The setup wizard (KDE dialogs via `kdialog`) installs the app and shortcuts for your user only: the app at `~/.local/bin/tricbar`, TricBar and uninstaller entries in the application menu at `~/.local/share/applications`, an icon, and an optional "reapply at login" setting. It does not create Desktop shortcuts. Requires KDE Plasma 6 and Python 3.9 or later. If PySide6 (used by the settings window) and `pip` are missing, Setup installs the distro's `pip` package using `apt`, `dnf`/`yum`, `pacman`, `zypper`, `apk`, `xbps`, `emerge`, or `urpmi`, depending on what's available; this step may ask for administrator authentication. It then downloads PySide6 (about 200 MB; an internet connection is required) to `~/.local/share/tricbar/lib` without installing PySide6 system-wide. This copy is removed when you uninstall TricBar.

Other Setup options: `--uninstall` (or use **TricBar - Uninstall** in the application menu or run `tricbar-uninstall`), `--extract DIR` (extract the app and icon), `--check` (verify the installer), `-y` (skip prompts), and `--tty` (text mode).

To build Setup from this repository, run `./build-setup.sh` (requires Python with Pillow to resize the icon).

## Usage

```bash
tricbar                                   # open the settings window
tricbar set --mode blur --color FFD60A --opacity 40 --blur 8
tricbar set --mode acrylic --color 000000 --opacity 50 --noise 8
tricbar set --mode clear                  # fully transparent
tricbar set --center 1                    # center task icons
tricbar set --startup 1                   # reapply the style at login
tricbar restore                           # restore the previous settings
tricbar status                            # show detected settings
tricbar --dry-run set --mode blur         # show commands without running them
```

Styles: `normal`, `clear`, `blur`, `acrylic`, and `color`. Settings are stored in `~/.config/tricbar/config.ini` (the same keys as the Windows version: `mode`, `color`, `opacity`, and `center`, plus `blur` and `noise`).

## What TricBar changes (and how to undo it manually)

| What | Location | How to undo |
|---|---|---|
| Plasma Styles `TricBar0` / `TricBar1` | `~/.local/share/plasma/desktoptheme/` | Run `plasma-apply-desktoptheme breeze-dark` (or choose your own theme) and delete both folders |
| KWin Blur | `kwinrc`: `[Plugins] blurEnabled`, `[Effect-blur] BlurStrength`, `NoiseStrength` | Run `tricbar restore`, or delete the keys with `kwriteconfig6 --delete` |
| Main panel position | Panel containing the Task Manager: bottom, full-width, and not floating | `tricbar restore` restores its previous position and mode |
| Two panel spacers (only with `--center 1`) | Added to the panel through the scripting API, one on each side of the Task Manager | `tricbar restore` |
| Previous settings | `~/.config/tricbar/state.json` | Read by `restore` |

If the panel looks wrong, the safest option is `tricbar restore`. If Plasma itself becomes unresponsive, restart it with `systemctl --user restart plasma-plasmashell.service` (or `plasmashell --replace &`).

## Limitations (please read)

- **The Plasma Style changes to "TricBar."** It only defines the panel background; everything else falls back to the default theme. If you use another Plasma Style, it is replaced while TricBar is active and restored by `restore`.
- **KWin Blur is global**: its strength and noise settings affect everything that requests blur, not just the panel. The Blur effect must be available in Desktop Effects.
- **Centering uses spacers**: the application launcher stays on the left and the system tray on the right; task icons are centered within the remaining space (they are exactly centered only when both sides have the same width). TricBar tracks the spacers it creates and removes them when you turn off centering or run `restore`. Existing spacers are not modified.
- Designed for **Plasma 6**. On Plasma 5, transparency may work, but centering is not supported (`lengthMode` is only available starting with Plasma 6.0).
- For more advanced customization, try the *Panel Colorizer* widget.


