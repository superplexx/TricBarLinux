#!/usr/bin/env bash
# Testa o Setup num HOME falso, com kdialog/qdbus6 simulados (nao toca no seu sistema).
set -euo pipefail
cd "$(dirname "$0")/.."
RUN="$(ls dist/TricBar-Setup-*.run | tail -1)"; RUN="$PWD/$RUN"
T="$(mktemp -d)"; trap 'rm -rf "$T"' EXIT
mkdir -p "$T/home/Desktop" "$T/shim"
cat > "$T/shim/kdialog" <<'EOF'
#!/usr/bin/env bash
case "$*" in
  *--checklist*) echo '"startup"' ;;
  *--progressbar*) echo "org.kde.kdialog-1 /ProgressDialog" ;;
esac
EOF
printf '#!/usr/bin/env bash\n' > "$T/shim/qdbus6"; chmod +x "$T/shim/"*
for tool in update-desktop-database gtk-update-icon-cache kbuildsycoca5 kbuildsycoca6; do
  printf '#!/usr/bin/env bash\nexit 0\n' > "$T/shim/$tool"
done
chmod +x "$T/shim/"*
run() { env HOME="$T/home" DISPLAY=:0 TRICBAR_ALLOW_ROOT=1 PATH="$T/shim:$PATH" "$@"; }
ok() { echo "ok   $1"; }; fail() { echo "FALHOU: $1"; exit 1; }

"$RUN" --check >/dev/null || fail "check"; ok "payload integro"
run "$RUN" --no-deps >/dev/null || fail "instalar"
for f in .local/bin/tricbar .local/bin/tricbar-uninstall .local/share/applications/tricbar.desktop \
         .local/share/applications/tricbar-uninstall.desktop \
         .local/share/icons/hicolor/256x256/apps/tricbar.png .local/share/tricbar/TricBar-Setup.run \
         .config/autostart/tricbar.desktop; do
  [ -e "$T/home/$f" ] || fail "faltou $f"; done; ok "arquivos instalados"
grep -q '^Name=TricBar - Uninstall$' "$T/home/.local/share/applications/tricbar-uninstall.desktop" \
  || fail "nome do atalho de desinstalação"; ok "atalho de desinstalação no menu"
[ ! -e "$T/home/Desktop/TricBar.desktop" ] || fail "atalho criado na Área de Trabalho"; ok "sem atalho na Área de Trabalho"
run "$T/home/.local/bin/tricbar" status | grep -q "Iniciar com a sessão: sim" || fail "status"; ok "app instalado roda"
# Simula um atalho criado por uma versão anterior; a atualização deve removê-lo.
printf 'legacy\n' > "$T/home/Desktop/TricBar.desktop"
printf '%s\n' "$T/home/Desktop/TricBar.desktop" >> "$T/home/.local/share/tricbar/install.manifest"
run "$RUN" --no-deps >/dev/null || fail "atualizar"; ok "atualizacao por cima"
[ ! -e "$T/home/Desktop/TricBar.desktop" ] || fail "atalho antigo da Área de Trabalho não removido"; ok "atalho antigo removido"
run "$T/home/.local/bin/tricbar-uninstall" >/dev/null || fail "desinstalar"
[ -z "$(find "$T/home" -type f)" ] || { find "$T/home" -type f; fail "sobrou arquivo"; }; ok "desinstalacao limpa"
cp "$RUN" "$T/bad.run"; printf x >> "$T/bad.run"
! "$T/bad.run" --check >/dev/null 2>&1 || fail "corrompido nao detectado"; ok "arquivo corrompido detectado"
echo "Tudo certo."
