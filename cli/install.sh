#!/usr/bin/env bash
#
# Seaglass CLI installer.
#
#   curl -fsSL https://raw.githubusercontent.com/drummel/seaglass-alpha/main/cli/install.sh | bash
#
# Downloads the right prebuilt binary for this OS/arch from GitHub Releases,
# verifies its checksum, and installs it to ~/.local/bin (override with
# SEAGLASS_INSTALL_DIR). Pin a version with SEAGLASS_VERSION=1.2.3.
#
# The binaries are fully static (CGO disabled), so the Linux build runs on both
# glibc and musl (Alpine) with no libc dependency.

set -euo pipefail

readonly REPO="${SEAGLASS_REPO:-drummel/seaglass-alpha}"
readonly REQUESTED_VERSION="${SEAGLASS_VERSION:-latest}"

info() { printf '==> %s\n' "$*" >&2; }
fail() { printf 'error: %s\n' "$*" >&2; exit 1; }

require_command() {
	command -v "$1" >/dev/null 2>&1 || fail "Missing required command: $1"
}

# Detect the release target for this OS + architecture.
detect_target() {
	local os arch
	os="$(uname -s)"
	arch="$(uname -m)"

	# Rosetta 2: an x86_64 process translated on Apple Silicon takes the arm64 build.
	if [[ "${os}" == "Darwin" && "${arch}" == "x86_64" ]]; then
		if [[ "$(sysctl -n sysctl.proc_translated 2>/dev/null)" == "1" ]]; then
			arch="arm64"
		fi
	fi

	case "${os}" in
	MINGW* | MSYS* | CYGWIN*)
		fail "This installer does not support Windows. Download the .zip from https://github.com/${REPO}/releases"
		;;
	esac

	case "${os}" in
	Darwin) TARGET_OS="darwin" ;;
	Linux) TARGET_OS="linux" ;;
	*) fail "Unsupported OS: ${os}" ;;
	esac

	case "${arch}" in
	x86_64 | amd64) TARGET_ARCH="amd64" ;;
	arm64 | aarch64) TARGET_ARCH="arm64" ;;
	*) fail "Unsupported architecture: ${arch}" ;;
	esac
}

detect_downloader() {
	if command -v curl >/dev/null 2>&1; then
		DOWNLOADER="curl"
	elif command -v wget >/dev/null 2>&1; then
		DOWNLOADER="wget"
	else
		fail "Either curl or wget is required but neither is installed"
	fi
}

download() {
	local url="$1" output="$2"
	if [[ "${DOWNLOADER}" == "curl" ]]; then
		curl -fsSL -o "${output}" "${url}"
	else
		wget -q -O "${output}" "${url}"
	fi
}

# Resolve "latest" to a concrete tag via the GitHub API, or normalize an
# explicit version to a v-prefixed tag.
resolve_tag() {
	if [[ "${REQUESTED_VERSION}" != "latest" ]]; then
		if [[ "${REQUESTED_VERSION}" == v* ]]; then
			printf '%s\n' "${REQUESTED_VERSION}"
		else
			printf 'v%s\n' "${REQUESTED_VERSION}"
		fi
		return
	fi
	local api="https://api.github.com/repos/${REPO}/releases/latest"
	local body
	body="$(download "${api}" /dev/stdout)" || fail "Could not query the latest release from ${api}"
	printf '%s\n' "${body}" | grep -m1 '"tag_name"' | sed -E 's/.*"tag_name" *: *"([^"]+)".*/\1/'
}

choose_install_dir() {
	if [[ -n "${SEAGLASS_INSTALL_DIR:-}" ]]; then
		INSTALL_DIR="${SEAGLASS_INSTALL_DIR}"
	else
		INSTALL_DIR="${HOME}/.local/bin"
	fi
	mkdir -p "${INSTALL_DIR}" 2>/dev/null || fail "Could not create ${INSTALL_DIR}. Set SEAGLASS_INSTALL_DIR to a writable directory."
	[[ -w "${INSTALL_DIR}" ]] || fail "${INSTALL_DIR} is not writable. Set SEAGLASS_INSTALL_DIR to a directory you can write to."
}

verify_checksum() {
	local dir="$1" archive="$2" checksums="$3"
	local tool
	if command -v sha256sum >/dev/null 2>&1; then
		tool="sha256sum"
	elif command -v shasum >/dev/null 2>&1; then
		tool="shasum -a 256"
	else
		info "No sha256 tool found; skipping checksum verification."
		return
	fi
	local expected actual
	expected="$(grep " ${archive}\$" "${checksums}" | awk '{print $1}')"
	[[ -n "${expected}" ]] || fail "No checksum entry for ${archive}"
	actual="$(cd "${dir}" && ${tool} "${archive}" | awk '{print $1}')"
	[[ "${expected}" == "${actual}" ]] || fail "Checksum mismatch for ${archive}"
}

main() {
	require_command uname
	require_command tar
	require_command mktemp
	detect_downloader
	detect_target
	choose_install_dir

	local tag version
	tag="$(resolve_tag)"
	[[ -n "${tag}" ]] || fail "Could not resolve a release tag."
	version="${tag#v}"

	local archive base url checksums_url
	archive="seaglass_${version}_${TARGET_OS}_${TARGET_ARCH}.tar.gz"
	base="https://github.com/${REPO}/releases/download/${tag}"
	url="${base}/${archive}"
	checksums_url="${base}/checksums.txt"

	local tmp
	tmp="$(mktemp -d)"
	trap 'rm -rf "${tmp}"' EXIT

	info "Downloading seaglass ${tag} (${TARGET_OS}/${TARGET_ARCH})"
	download "${url}" "${tmp}/${archive}" || fail "Failed to download ${url}"
	if download "${checksums_url}" "${tmp}/checksums.txt" 2>/dev/null; then
		verify_checksum "${tmp}" "${archive}" "${tmp}/checksums.txt"
	else
		info "checksums.txt not found; skipping verification."
	fi

	tar -xzf "${tmp}/${archive}" -C "${tmp}"
	[[ -f "${tmp}/seaglass" ]] || fail "Archive did not contain a seaglass binary"
	install -m 0755 "${tmp}/seaglass" "${INSTALL_DIR}/seaglass"

	printf '\n  Installed seaglass %s to %s/seaglass\n\n' "${tag}" "${INSTALL_DIR}" >&2
	case ":${PATH}:" in
	*":${INSTALL_DIR}:"*) ;;
	*)
		printf '  Add it to your PATH:\n\n    export PATH="%s:$PATH"\n\n' "${INSTALL_DIR}" >&2
		;;
	esac
	cat >&2 <<'NEXT'
  Get started:

    seaglass auth login     Link this CLI to your Seaglass account
    seaglass search <query> Read your memory
    seaglass --help         See all commands

NEXT
}

main "$@"
