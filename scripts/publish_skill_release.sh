#!/usr/bin/env bash
set -euo pipefail

: "${GITHUB_REF_NAME:?GITHUB_REF_NAME is required}"
: "${NOTES_FILE:?NOTES_FILE is required}"

gh_cli="${GH_CLI:-gh}"
title="BrandBAI Skills ${GITHUB_REF_NAME}"

shopt -s nullglob
assets=(dist/*.zip dist/*.sha256)
if (( ${#assets[@]} == 0 )); then
  echo "No release assets found in dist" >&2
  exit 1
fi

if "${gh_cli}" release view "${GITHUB_REF_NAME}" >/dev/null 2>&1; then
  echo "Updating existing GitHub Release ${GITHUB_REF_NAME}"
  "${gh_cli}" release edit "${GITHUB_REF_NAME}" \
    --title "${title}" \
    --notes-file "${NOTES_FILE}"
  "${gh_cli}" release upload "${GITHUB_REF_NAME}" \
    "${assets[@]}" \
    --clobber
else
  echo "Creating GitHub Release ${GITHUB_REF_NAME}"
  "${gh_cli}" release create "${GITHUB_REF_NAME}" \
    "${assets[@]}" \
    --verify-tag \
    --title "${title}" \
    --notes-file "${NOTES_FILE}"
fi
