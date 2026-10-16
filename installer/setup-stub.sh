#!/usr/bin/env bash
# =============================================================================
#  TricBar Setup @VERSION@  -  instalador unico para o KDE Plasma
#
#  Este arquivo e o instalador inteiro: o script abaixo + o app compactado no
#  final (depois da linha __TRICBAR_PAYLOAD__). O app e instalado por usuario;
#  instalar o pip da distro pode pedir autenticacao administrativa.
#
#  Uso:
#    ./TricBar-Setup-@VERSION@.run              abre o assistente (instala / atualiza)
#    ./TricBar-Setup-@VERSION@ --uninstall  desinstala
#    ./TricBar-Setup-@VERSION@ --help       todas as opcoes
# =============================================================================

APP_NAME="TricBar"
APP_VERSION="@VERSION@"
PAYLOAD_SHA256="@SHA256@"
TITLE="Instalador do TricBar $APP_VERSION"

SELF="$(readlink -f "$0" 2>/dev/null || echo "$0")"
DATA_HOME="${XDG_DATA_HOME:-$HOME/.local/share}"
CONFIG_HOME="${XDG_CONFIG_HOME:-$HOME/.config}"
BIN_DIR="$HOME/.local/bin"
APP_DIR="$DATA_HOME/tricbar"
MANIFEST="$APP_DIR/install.manifest"
ICON_SIZES="256 128 64 48 32"

UI=""            # kdialog | zenity | tty
ASSUME_YES=0
NO_DEPS=0
SEL=" "
WARNINGS=""
TMP=""
PROG_REF=""
PROG_FIFO=""

# ------------------------------------------------------------------ utilidades
cleanup() {
  [ -n "$TMP" ] && rm -rf "$TMP"
  prog_end
}
trap cleanup EXIT

has() { command -v "$1" >/dev/null 2>&1; }
warn_add() { WARNINGS="$WARNINGS
- $1"; }

payload_line() { awk '/^__TRICBAR_PAYLOAD__$/ { print NR + 1; exit }' "$SELF"; }
payload() { tail -n +"$(payload_line)" "$SELF"; }

# ------------------------------------------------------------------ interface
ui_pick() {
  if [ "$ASSUME_YES" = 1 ] || [ "$UI" = tty ]; then UI=tty; return; fi
  if [ -n "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ]; then
    if has kdialog; then UI=kdialog; return; fi
    if has zenity; then UI=zenity; return; fi
  fi
  if [ -t 0 ] && [ -t 1 ]; then UI=tty; return; fi
  # sem janela e sem terminal (ex.: duplo clique): reabre dentro de um terminal
  for t in konsole xterm gnome-terminal x-terminal-emulator; do
    has "$t" || continue
    case $t in
      gnome-terminal) exec gnome-terminal -- "$SELF" --tty "${ORIG_ARGS[@]}" ;;
      *) exec "$t" -e "$SELF" --tty "${ORIG_ARGS[@]}" ;;
    esac
  done
  echo "TricBar: nao achei kdialog, zenity nem um terminal. Rode no terminal: $SELF" >&2
  exit 1
}

ui_msg() {   # $1 = texto
  case $UI in
    kdialog) kdialog --title "$TITLE" --msgbox "$1" ;;
    zenity)  zenity --info --no-markup --title="$TITLE" --text="$1" --width=440 ;;
    *)       printf '\n%s\n' "$1" ;;
  esac
}

ui_error() {
  case $UI in
    kdialog) kdialog --title "$TITLE" --error "$1" ;;
    zenity)  zenity --error --no-markup --title="$TITLE" --text="$1" --width=440 ;;
    *)       printf '\nERRO: %s\n' "$1" >&2 ;;
  esac
}

ui_yesno() { # $1 texto, $2 rotulo "sim", $3 rotulo "nao"; retorna 0 se "sim"
  case $UI in
    kdialog) kdialog --title "$TITLE" --yes-label "${2:-Sim}" --no-label "${3:-Não}" --yesno "$1" ;;
    zenity)  zenity --question --no-markup --title="$TITLE" --text="$1" \
                    --ok-label="${2:-Sim}" --cancel-label="${3:-Não}" --width=440 ;;
    *)
      printf '\n%s\n' "$1"
      [ "$ASSUME_YES" = 1 ] && return 0
      read -r -p "[S/n] " a
      case "$a" in n* | N*) return 1 ;; *) return 0 ;; esac ;;
  esac
}

ui_options() {   # preenche SEL com as opcoes marcadas; retorna 1 se cancelou
  local out
  case $UI in
    kdialog)
      out="$(kdialog --title "$TITLE" --checklist "O TricBar e o desinstalador serão adicionados ao menu de aplicativos:" \
        startup "Reaplicar o estilo do painel ao iniciar a sessão" on \
        open    "Abrir o TricBar ao terminar" on)" || return 1
      SEL=" $(printf '%s' "$out" | tr -d '"') " ;;
    zenity)
      out="$(zenity --list --checklist --title="$TITLE" --text="O TricBar e o desinstalador serão adicionados ao menu de aplicativos:" --width=480 --height=280 \
        --column="" --column="id" --column="Opção" --hide-column=2 --print-column=2 --separator=" " \
        TRUE startup "Reaplicar o estilo do painel ao iniciar a sessão" \
        TRUE open "Abrir o TricBar ao terminar")" || return 1
      SEL=" $out " ;;
    *)
      SEL=" "
      if [ "$ASSUME_YES" = 1 ]; then SEL=" startup "; return 0; fi
      ui_yesno "Reaplicar o estilo do painel ao iniciar a sessão?" && SEL="$SEL startup"
      ui_yesno "Abrir o TricBar ao terminar?" && SEL="$SEL open"
      SEL="$SEL " ;;
  esac
  return 0
}

QDBUS=""
prog_start() {   # $1 = texto
  case $UI in
    kdialog)
      QDBUS="$(command -v qdbus6 || command -v qdbus-qt6 || command -v qdbus)"
      [ -n "$QDBUS" ] && PROG_REF="$(kdialog --title "$TITLE" --progressbar "$1" 100 2>/dev/null)" ;;
    zenity)
      PROG_FIFO="$(mktemp -u)"; mkfifo "$PROG_FIFO"
      zenity --progress --no-cancel --auto-close --title="$TITLE" --text="$1" --width=420 <"$PROG_FIFO" &
      exec 9>"$PROG_FIFO" ;;
    *) printf '%s\n' "$1" ;;
  esac
}
prog_set() {     # $1 = porcentagem, $2 = texto
  case $UI in
    kdialog)
      [ -n "$PROG_REF" ] || return 0
      # shellcheck disable=SC2086
      { $QDBUS $PROG_REF Set "" value "$1"; $QDBUS $PROG_REF setLabelText "$2"; } >/dev/null 2>&1 ;;
    zenity) [ -n "$PROG_FIFO" ] && { echo "$1" >&9; echo "# $2" >&9; } 2>/dev/null ;;
    *) printf '  [%3s%%] %s\n' "$1" "$2" ;;
  esac
}
prog_end() {
  if [ -n "$PROG_REF" ]; then
    # shellcheck disable=SC2086
    $QDBUS $PROG_REF close >/dev/null 2>&1; PROG_REF=""
  fi
  if [ -n "$PROG_FIFO" ]; then
    exec 9>&- 2>/dev/null; rm -f "$PROG_FIFO"; PROG_FIFO=""
  fi
}

# ------------------------------------------------------------------ dependencias
qt_binding_ok() {
  python3 -c 'import PySide6.QtWidgets' 2>/dev/null || python3 -c 'import PyQt6.QtWidgets' 2>/dev/null \
    || PYTHONPATH="$APP_DIR/lib${PYTHONPATH:+:$PYTHONPATH}" python3 -c 'import PySide6.QtWidgets' 2>/dev/null
}

PIP_INSTALL_ERROR=""

run_privileged() {
  if [ "$(id -u)" = 0 ]; then
    "$@"
  elif [ "$UI" != tty ] && has pkexec; then
    pkexec "$@"
  elif has sudo; then
    sudo "$@"
  elif has doas; then
    doas "$@"
  else
    PIP_INSTALL_ERROR="Não achei pkexec, sudo nem doas para instalar o pip da distro."
    return 1
  fi
}

install_system_pip() {
  local os_release=/etc/os-release id="" id_like="" distro=""
  local -a command=()

  if [ -r "$os_release" ]; then
    id="$(sed -n 's/^ID=//p' "$os_release" | head -n 1 | tr -d '"')"
    id_like="$(sed -n 's/^ID_LIKE=//p' "$os_release" | head -n 1 | tr -d '"')"
  fi
  distro=" ${id,,} ${id_like,,} "

  case "$distro" in
    *" debian "*|*" ubuntu "*|*" linuxmint "*|*" pop "*|*" kali "*|*" raspbian "*)
      has apt-get || { PIP_INSTALL_ERROR="Não achei apt-get para instalar python3-pip."; return 1; }
      command=(apt-get install -y python3-pip) ;;
    *" fedora "*|*" rhel "*|*" centos "*|*" rocky "*|*" almalinux "*)
      if has dnf; then command=(dnf install -y python3-pip)
      elif has yum; then command=(yum install -y python3-pip)
      else PIP_INSTALL_ERROR="Não achei dnf nem yum para instalar python3-pip."; return 1; fi ;;
    *" arch "*|*" manjaro "*|*" endeavouros "*)
      has pacman || { PIP_INSTALL_ERROR="Não achei pacman para instalar python-pip."; return 1; }
      command=(pacman -S --needed --noconfirm python-pip) ;;
    *" opensuse"*|*" suse "*)
      has zypper || { PIP_INSTALL_ERROR="Não achei zypper para instalar python3-pip."; return 1; }
      command=(zypper --non-interactive install python3-pip) ;;
    *" alpine "*)
      has apk || { PIP_INSTALL_ERROR="Não achei apk para instalar py3-pip."; return 1; }
      command=(apk add py3-pip) ;;
    *" void "*)
      has xbps-install || { PIP_INSTALL_ERROR="Não achei xbps-install para instalar python3-pip."; return 1; }
      command=(xbps-install -Sy python3-pip) ;;
    *" gentoo "*)
      has emerge || { PIP_INSTALL_ERROR="Não achei emerge para instalar dev-python/pip."; return 1; }
      command=(emerge --ask=n dev-python/pip) ;;
    *" mageia "*)
      has urpmi || { PIP_INSTALL_ERROR="Não achei urpmi para instalar python3-pip."; return 1; }
      command=(urpmi --auto python3-pip) ;;
    *)
      PIP_INSTALL_ERROR="Não reconheci uma distro compatível para instalar o pip automaticamente (ID=${id:-desconhecido}; ID_LIKE=${id_like:-indisponível}). Instale o pacote pip da sua distro e tente novamente."
      return 1 ;;
  esac

  prog_set 25 "Instalando pip pela distro (${id:-${id_like:-Linux}})..."
  if ! run_privileged "${command[@]}"; then
    PIP_INSTALL_ERROR="${PIP_INSTALL_ERROR:-Falha ao instalar o pip da distro.}"
    return 1
  fi
  if ! python3 -m pip --version >/dev/null 2>&1 && ! has pip3 && ! has pip; then
    PIP_INSTALL_ERROR="O gerenciador de pacotes terminou, mas o pip continua indisponível para python3."
    return 1
  fi
}

# Instala o PySide6 numa pasta so do TricBar (~/.local/share/tricbar/lib) com o pip.
install_qt_private() {
  local -a pipcmd=()
  if python3 -m pip --version >/dev/null 2>&1; then pipcmd=(python3 -m pip)
  elif has pip3; then pipcmd=(pip3)
  elif has pip; then pipcmd=(pip)
  else return 2; fi
  mkdir -p "$APP_DIR/lib" || return 1
  "${pipcmd[@]}" install --quiet --disable-pip-version-check --target "$APP_DIR/lib" PySide6-Essentials \
    || "${pipcmd[@]}" install --quiet --disable-pip-version-check --break-system-packages --target "$APP_DIR/lib" PySide6-Essentials
}

check_deps() {
  if ! has python3 || ! python3 -c 'import sys; sys.exit(sys.version_info < (3, 9))' 2>/dev/null; then
    ui_error "O TricBar precisa do Python 3.9 ou mais novo (python3), que não foi encontrado.
Instale o pacote python3 da sua distro e rode o Setup de novo."
    return 1
  fi

  if ! qt_binding_ok && [ "$NO_DEPS" = 0 ]; then
    if ui_yesno "Para abrir a janela de configurações o TricBar usa o PySide6 (Qt para Python), que não está instalado.

Posso baixar uma cópia só para o TricBar (cerca de 200 MB, precisa de internet). Se o pip não estiver instalado, o Setup instala o pacote correspondente à sua distro e pode pedir autenticação de administrador. O PySide6 fica em $APP_DIR/lib e some quando você desinstala." "Baixar" "Pular"; then
      prog_set 25 "Baixando o PySide6 (pode demorar alguns minutos)..."
      if ! python3 -m pip --version >/dev/null 2>&1 && ! has pip3 && ! has pip; then
        if ! install_system_pip; then
          ui_error "$PIP_INSTALL_ERROR"
          return 1
        fi
      fi
      if install_qt_private; then
        :
      else
        local qt_status=$?
        rm -rf "$APP_DIR/lib"
        if [ "$qt_status" = 2 ]; then
          ui_error "O pip continua indisponível depois da instalação pela distro. $PIP_INSTALL_ERROR"
          return 1
        fi
        warn_add "Falha ao baixar o PySide6 (sem internet?). Rode o Setup de novo quando tiver conexão."
      fi
    fi
  fi
  if ! qt_binding_ok; then
    warn_add "PySide6 não instalado: a janela de configurações não abre."
  fi
  has kwriteconfig6 || has kwriteconfig5 || warn_add "kwriteconfig6 não encontrado (pacote kconfig)."
  has plasma-apply-desktoptheme || warn_add "plasma-apply-desktoptheme não encontrado (pacote plasma-workspace): sem ele o painel não muda."
  has qdbus6 || has qdbus-qt6 || has qdbus || has busctl || warn_add "qdbus6 não encontrado (pacote qt6-tools)."
  return 0
}

# ------------------------------------------------------------------ instalar
verify_payload() {
  local sum
  sum="$(payload | sha256sum | cut -d' ' -f1)"
  [ "$sum" = "$PAYLOAD_SHA256" ]
}

refresh_caches() {
  has update-desktop-database && update-desktop-database "$DATA_HOME/applications" >/dev/null 2>&1
  has gtk-update-icon-cache && gtk-update-icon-cache -q -f -t "$DATA_HOME/icons/hicolor" >/dev/null 2>&1
  if has kbuildsycoca6; then kbuildsycoca6 --noincremental >/dev/null 2>&1
  elif has kbuildsycoca5; then kbuildsycoca5 --noincremental >/dev/null 2>&1; fi
  return 0
}

exec_field() {   # valor seguro para Exec= (aspas se tiver espaco)
  case "$1" in *" "*) printf '"%s"' "$1" ;; *) printf '%s' "$1" ;; esac
}

do_install() {
  TMP="$(mktemp -d)" || { ui_error "Não consegui criar uma pasta temporária."; return 1; }
  payload | tar -xz -C "$TMP" || { ui_error "Falha ao extrair o instalador (arquivo incompleto?)."; return 1; }

  local files=() f size
  if [ -f "$MANIFEST" ]; then
    while IFS= read -r f; do
      case "$f" in "$HOME"/*/TricBar.desktop) rm -f "$f" ;; esac
    done < "$MANIFEST"
  fi
  mkdir -p "$BIN_DIR" "$APP_DIR" "$DATA_HOME/applications" || return 1

  prog_set 45 "Copiando o aplicativo..."
  install -m 755 "$TMP/tricbar.py" "$BIN_DIR/tricbar" || return 1
  files+=("$BIN_DIR/tricbar")

  cat > "$BIN_DIR/tricbar-uninstall" <<EOF
#!/usr/bin/env bash
exec "$APP_DIR/TricBar-Setup.run" --uninstall "\$@"
EOF
  chmod 755 "$BIN_DIR/tricbar-uninstall"
  files+=("$BIN_DIR/tricbar-uninstall")

  # copia do proprio instalador: serve para desinstalar e para reparar depois
  if ! [ "$SELF" -ef "$APP_DIR/TricBar-Setup.run" ]; then
    install -m 755 "$SELF" "$APP_DIR/TricBar-Setup.run" || return 1
  fi
  files+=("$APP_DIR/TricBar-Setup.run")
  for f in LICENSE README.md; do
    [ -f "$TMP/$f" ] && install -m 644 "$TMP/$f" "$APP_DIR/$f" && files+=("$APP_DIR/$f")
  done

  prog_set 60 "Instalando ícones e atalhos..."
  for size in $ICON_SIZES; do
    [ -f "$TMP/icons/tricbar-$size.png" ] || continue
    mkdir -p "$DATA_HOME/icons/hicolor/${size}x${size}/apps"
    install -m 644 "$TMP/icons/tricbar-$size.png" "$DATA_HOME/icons/hicolor/${size}x${size}/apps/tricbar.png"
    files+=("$DATA_HOME/icons/hicolor/${size}x${size}/apps/tricbar.png")
  done

  local bin_exec; bin_exec="$(exec_field "$BIN_DIR/tricbar")"
  local unin_exec; unin_exec="$(exec_field "$BIN_DIR/tricbar-uninstall")"
  sed -e "s|@BIN@-uninstall|$unin_exec|g" -e "s|@BIN@|$bin_exec|g" "$TMP/tricbar.desktop" \
    > "$DATA_HOME/applications/tricbar.desktop" || return 1
  files+=("$DATA_HOME/applications/tricbar.desktop")

  cat > "$DATA_HOME/applications/tricbar-uninstall.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=TricBar - Uninstall
Comment=Desinstalar o TricBar e restaurar o painel
Exec=$unin_exec
Icon=tricbar
Terminal=false
Categories=Settings;DesktopSettings;Utility;
EOF
  files+=("$DATA_HOME/applications/tricbar-uninstall.desktop")

  prog_set 80 "Finalizando..."
  case "$SEL" in
    *" startup "*) "$BIN_DIR/tricbar" startup on >/dev/null 2>&1 || warn_add "Não consegui ligar o início com a sessão." ;;
    *)             "$BIN_DIR/tricbar" startup off >/dev/null 2>&1 ;;
  esac

  printf '%s\n' "${files[@]}" > "$MANIFEST"
  refresh_caches
  prog_set 100 "Pronto."
  return 0
}

# ------------------------------------------------------------------ desinstalar
do_uninstall() {
  if [ ! -f "$MANIFEST" ] && [ ! -x "$BIN_DIR/tricbar" ]; then
    ui_msg "O TricBar não parece estar instalado para este usuário."
    return 0
  fi
  ui_yesno "Desinstalar o TricBar?

O painel do Plasma será devolvido ao que era antes (estilo, desfoque e posição) e todos os arquivos do TricBar serão removidos." "Desinstalar" "Cancelar" || return 0

  if [ -x "$BIN_DIR/tricbar" ]; then
    "$BIN_DIR/tricbar" restore >/dev/null 2>&1
    "$BIN_DIR/tricbar" startup off >/dev/null 2>&1
  fi
  if [ -f "$MANIFEST" ]; then
    while IFS= read -r f; do
      [ -n "$f" ] && rm -f "$f"
    done < "$MANIFEST"
  fi
  rm -f "$BIN_DIR/tricbar" "$BIN_DIR/tricbar-uninstall" \
    "$DATA_HOME/applications/tricbar-uninstall.desktop" "$CONFIG_HOME/autostart/tricbar.desktop"
  rm -rf "$CONFIG_HOME/tricbar"
  rm -f "$MANIFEST"
  rm -rf "$APP_DIR/lib"
  for size in $ICON_SIZES; do rmdir "$DATA_HOME/icons/hicolor/${size}x${size}/apps" "$DATA_HOME/icons/hicolor/${size}x${size}" 2>/dev/null; done
  rmdir "$APP_DIR" 2>/dev/null
  # a copia do instalador (esta, se rodando de la) some por ultimo
  rm -f "$APP_DIR/TricBar-Setup.run"
  rmdir "$APP_DIR" 2>/dev/null
  refresh_caches
  ui_msg "TricBar desinstalado. O painel voltou ao padrão."
  return 0
}

# ------------------------------------------------------------------ principal
usage() {
  cat <<EOF
TricBar Setup $APP_VERSION - instalador para o KDE Plasma (sem root)

  $(basename "$SELF")                 abre o assistente (instala ou atualiza)
  $(basename "$SELF") --uninstall     desinstala (restaura o painel antes)
  $(basename "$SELF") --extract DIR   so extrai os arquivos do app para DIR
  $(basename "$SELF") --check         confere se o arquivo esta integro

Opcoes:
  -y, --yes, --silent   sem perguntas (instala com o padrao, no terminal)
  --tty                 usa o modo texto em vez de janelas
  --no-deps             nao tenta baixar o PySide6
  -h, --help            esta ajuda
  -V, --version         versao
EOF
}

main() {
  local mode=install extract_dir=""
  ORIG_ARGS=("$@")
  while [ $# -gt 0 ]; do
    case "$1" in
      -h | --help) usage; return 0 ;;
      -V | --version) echo "TricBar Setup $APP_VERSION"; return 0 ;;
      --uninstall | --remove) mode=uninstall ;;
      --check) mode=check ;;
      --extract) mode=extract; extract_dir="${2:-}"; shift ;;
      -y | --yes | --silent) ASSUME_YES=1 ;;
      --tty) UI=tty ;;
      --no-deps) NO_DEPS=1 ;;
      *) echo "Opção desconhecida: $1" >&2; usage >&2; return 2 ;;
    esac
    shift
  done

  for t in tar gzip sha256sum awk tail sed mktemp; do
    has "$t" || { echo "Faltando o comando '$t'." >&2; return 1; }
  done

  if [ "$mode" = check ]; then
    if verify_payload; then echo "OK: arquivo íntegro."; return 0; fi
    echo "ERRO: arquivo corrompido." >&2; return 1
  fi

  if [ "$mode" = extract ]; then
    [ -n "$extract_dir" ] || { echo "Uso: --extract PASTA" >&2; return 2; }
    verify_payload || { echo "ERRO: arquivo corrompido." >&2; return 1; }
    mkdir -p "$extract_dir" && payload | tar -xz -C "$extract_dir" && echo "Extraído em $extract_dir"
    return $?
  fi

  if [ "$(id -u)" = 0 ] && [ "$ASSUME_YES" = 0 ] && [ -z "${TRICBAR_ALLOW_ROOT:-}" ]; then
    echo "Não rode o instalador como root: o TricBar é instalado para o seu usuário." >&2
    return 1
  fi

  ui_pick

  if [ "$mode" = uninstall ]; then do_uninstall; return $?; fi

  if ! verify_payload; then
    ui_error "Este instalador está corrompido (a verificação falhou). Baixe o arquivo de novo."
    return 1
  fi

  local updating=0
  [ -f "$MANIFEST" ] && updating=1

  local intro="Este assistente instala o TricBar $APP_VERSION para o seu usuário.

O TricBar deixa o painel do KDE Plasma transparente, com Blur, Acrylic ou numa cor única, e pode centralizar o painel como um dock. Nada fica rodando em segundo plano.

Não precisa de senha de administrador nem de pacotes da sua distro."
  [ "$updating" = 1 ] && intro="Já existe um TricBar instalado. Este assistente vai atualizá-lo para a versão $APP_VERSION. Suas configurações são mantidas.

$intro"
  ui_yesno "$intro" "$([ "$updating" = 1 ] && echo Atualizar || echo Instalar)" "Cancelar" || return 0

  if ! { [ "${XDG_CURRENT_DESKTOP:-}" != "${XDG_CURRENT_DESKTOP/KDE/}" ] || has plasmashell; }; then
    ui_yesno "Não detectei o KDE Plasma nesta sessão. O TricBar só funciona no Plasma.

Instalar mesmo assim?" "Instalar mesmo assim" "Cancelar" || return 0
  fi

  ui_options || return 0

  prog_start "Preparando..."
  prog_set 10 "Conferindo dependências..."
  if ! check_deps; then prog_end; return 1; fi
  prog_set 40 "Instalando..."
  if ! do_install; then prog_end; ui_error "A instalação falhou. Nada foi alterado no seu painel."; return 1; fi
  prog_end

  local done_msg="TricBar $APP_VERSION instalado com sucesso.

Abra o TricBar pelo menu de aplicativos (procure por \"TricBar\")."
  case "$(printf '%s' ":$PATH:")" in *":$BIN_DIR:"*) ;; *)
    done_msg="$done_msg
Para usar no terminal, adicione $BIN_DIR ao PATH." ;; esac
  [ -n "$WARNINGS" ] && done_msg="$done_msg

Avisos:$WARNINGS"
  done_msg="$done_msg

Para desinstalar, procure por \"TricBar - Uninstall\" no menu de aplicativos."
  ui_msg "$done_msg"

  case "$SEL" in *" open "*)
    ( setsid "$BIN_DIR/tricbar" >/dev/null 2>&1 & ) ;;
  esac
  return 0
}

main "$@"
exit $?
__TRICBAR_PAYLOAD__
