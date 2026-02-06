#!/usr/bin/env bash
set -euo pipefail

log() {
  echo "[sqlserver-cli] $*"
}

ok() {
  echo "[OK] $*"
}

doing() {
  echo "[..] $*"
}

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Erro: comando '$1' nao encontrado." >&2
    exit 1
  fi
}

require_cmd apt-get
require_cmd curl

pkg_installed() {
  dpkg -s "$1" >/dev/null 2>&1
}

ensure_pkgs() {
  local missing=()
  for p in "$@"; do
    if pkg_installed "$p"; then
      ok "$p"
    else
      missing+=("$p")
    fi
  done
  if [[ ${#missing[@]} -gt 0 ]]; then
    doing "Instalando: ${missing[*]}"
    sudo apt-get install -y "${missing[@]}"
    for p in "${missing[@]}"; do
      ok "$p"
    done
  fi
}

pip_pkg_installed() {
  python3 -m pip show "$1" >/dev/null 2>&1
}

ensure_pip_pkg() {
  local p="$1"
  if pip_pkg_installed "$p"; then
    ok "pip:$p"
  else
    doing "pip install $p"
    python3 -m pip install "$p"
    ok "pip:$p"
  fi
}

install_pyodbc() {
  if pkg_installed python3-pyodbc; then
    ok "python3-pyodbc"
    return 0
  fi
  doing "Instalando: python3-pyodbc (apt)"
  if sudo apt-get install -y python3-pyodbc; then
    ok "python3-pyodbc"
    return 0
  fi

  # fallback pip
  doing "Falhou via apt. Usando pip para pyodbc..."
  ensure_pkgs build-essential python3-dev unixodbc-dev
  ensure_pip_pkg pyodbc
}

# Detect Ubuntu base (Linux Mint usa Ubuntu como base)
source /etc/os-release

ubuntu_ver=""
if [[ "${ID:-}" == "linuxmint" ]]; then
  codename="${UBUNTU_CODENAME:-${VERSION_CODENAME:-}}"
  case "$codename" in
    noble) ubuntu_ver="24.04" ;;
    jammy) ubuntu_ver="22.04" ;;
    focal) ubuntu_ver="20.04" ;;
    bionic) ubuntu_ver="18.04" ;;
    *)
      echo "Erro: codename Ubuntu desconhecido para Linux Mint: '$codename'" >&2
      exit 1
      ;;
  esac
elif [[ "${ID:-}" == "ubuntu" ]]; then
  ubuntu_ver="${VERSION_ID:-}"
elif [[ "${ID_LIKE:-}" == *"ubuntu"* ]]; then
  ubuntu_ver="${VERSION_ID:-}"
fi

if [[ -z "$ubuntu_ver" ]]; then
  echo "Erro: distribuicao nao suportada. Use Ubuntu ou Linux Mint." >&2
  exit 1
fi

case "$ubuntu_ver" in
  24.04|22.04|20.04|18.04) ;; 
  *)
    echo "Erro: Ubuntu '$ubuntu_ver' nao suportado por este instalador." >&2
    exit 1
    ;;
 esac

log "Ubuntu base detectado: $ubuntu_ver"
log "Instalando dependencias..."
sudo apt-get update
ensure_pkgs ca-certificates curl gnupg
ensure_pkgs zenity

log "Baixando repositorio da Microsoft..."
tmpdir="$(mktemp -d)"
trap 'rm -rf "$tmpdir"' EXIT
cd "$tmpdir"

curl -sSL -O "https://packages.microsoft.com/config/ubuntu/${ubuntu_ver}/packages-microsoft-prod.deb"
sudo dpkg -i packages-microsoft-prod.deb

log "Instalando Python e ODBC..."
sudo apt-get update
ensure_pkgs python3 python3-pip python3-venv

log "Instalando msodbcsql18 e unixodbc-dev..."
sudo apt-get update
if pkg_installed msodbcsql18; then
  ok "msodbcsql18"
else
  doing "Instalando: msodbcsql18"
  sudo ACCEPT_EULA=Y apt-get install -y msodbcsql18
  ok "msodbcsql18"
fi
ensure_pkgs unixodbc-dev

log "Opcional: instalando mssql-tools18..."
if pkg_installed mssql-tools18; then
  ok "mssql-tools18"
else
  doing "Instalando: mssql-tools18"
  sudo ACCEPT_EULA=Y apt-get install -y mssql-tools18
  ok "mssql-tools18"
fi

if ! grep -q "mssql-tools18/bin" "$HOME/.bashrc"; then
  echo 'export PATH="$PATH:/opt/mssql-tools18/bin"' >> "$HOME/.bashrc"
  log "PATH atualizado em ~/.bashrc (abra um novo terminal)."
fi

log "Criando atalho na area de trabalho..."
desktop_dir="$HOME/Desktop"
if [[ -f "$HOME/.config/user-dirs.dirs" ]]; then
  # shellcheck disable=SC1090
  source "$HOME/.config/user-dirs.dirs"
  if [[ -n "${XDG_DESKTOP_DIR:-}" ]]; then
    desktop_dir="$XDG_DESKTOP_DIR"
  fi
fi

app_dir="/home/andrefelipe/projetos/sqlserver-cli"
icon_src="$app_dir/assets/jupyter-ssms.svg"

log "Instalando icone..."
icon_dir="$HOME/.local/share/icons/hicolor/scalable/apps"
mkdir -p "$icon_dir"
if [[ -f "$icon_src" ]]; then
  cp -f "$icon_src" "$icon_dir/jupyter-ssms.svg"
fi

if command -v gtk-update-icon-cache >/dev/null 2>&1; then
  gtk-update-icon-cache -f "$HOME/.local/share/icons/hicolor" >/dev/null 2>&1 || true
fi
mkdir -p "$desktop_dir"
desktop_file="$desktop_dir/Jupyter-SSMS.desktop"
cat > "$desktop_file" <<EOF
[Desktop Entry]
Type=Application
Name=Jupyter-SSMS
Comment=SQL Server TUI (Io v1.06022026)
Exec=python3 $app_dir/sqlserver_cli.py
Path=$app_dir
Terminal=true
Icon=jupyter-ssms
Categories=Development;Database;
EOF
chmod +x "$desktop_file"

mkdir -p "$HOME/.local/share/applications"
cp -f "$desktop_file" "$HOME/.local/share/applications/jupyter-ssms.desktop"

log "Atalho criado em: $desktop_file"
log "Instalando dependencias Python..."
install_pyodbc

log "Concluido. Verifique com: odbcinst -q -d"
