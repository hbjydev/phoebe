#!/usr/bin/env sh

apt update && apt install -y unzip

mkdir -p "/opt/spt/user/mods" && chown -R 1000:1000 "/opt/spt/user"

download_mod() {
  local mod_name="$1"
  local mod_version="$2"
  local mod_url="$3"

  echo "Installing ${mod_name} v${mod_version}..."

  local workdir="$(mktemp -d)"
  local workdir_mods="${workdir}/SPT_Runtime/user/mods/${mod_name}"
  local install_mods="/opt/spt/user/mods/${mod_name}"

  if [[ ! -d "${install_mods}" ]]; then
    echo "Mod not found, downloading..."
    curl -L -o /tmp/${mod_name}.zip "${mod_url}"
    unzip -q /tmp/${mod_name}.zip -d "${workdir}"
    if [[ -d "${workdir_mods}" ]]; then
      mv "${workdir_mods}" "${install_mods}"
    else
      echo "Error: Mod directory not found in the downloaded archive."
      rm -rf "${workdir}"
      exit 1
    fi
    echo "${mod_version}" > "${install_mods}/version.txt"
  fi

  chown -R 1000:1000 "${install_mods}"

  echo "Mod ${mod_name} v${mod_version} installed successfully."
  rm -rf "${workdir}"
}

FIKA_VERSION="2.4.1"
download_mod "fika-server" "${FIKA_VERSION}" "https://github.com/project-fika/Fika-Server-CSharp/releases/download/v${FIKA_VERSION}/Fika.Server.Release.${FIKA_VERSION}.zip"

SAIN_VERSION="4.5.1"
download_mod "Solarint-SAIN-ServerMod" "${SAIN_VERSION}" "https://github.com/ArchangelWTF/SAIN/releases/download/v${SAIN_VERSION}/SAIN.${SAIN_VERSION}.zip"

SMTM_VERSION="3.0.2"
download_mod "swiftxp-showmethemoney" "${SMTM_VERSION}" "https://github.com/mattpsvreis/spt-show-me-the-money/releases/download/${SMTM_VERSION}/ShowMeTheMoney-${SMTM_VERSION}-SPT-4.1.5.zip"