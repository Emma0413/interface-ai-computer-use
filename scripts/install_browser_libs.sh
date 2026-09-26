#!/usr/bin/env bash
set -euo pipefail

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
work_dir=$(mktemp -d)
trap 'rm -rf "$work_dir"' EXIT

cd "$work_dir"
apt-get download libnspr4 libnss3 libasound2
mkdir -p "$repo_root/vendor/runtime-libs"
for package in ./*.deb; do
  dpkg-deb -x "$package" "$repo_root/vendor/runtime-libs"
done
